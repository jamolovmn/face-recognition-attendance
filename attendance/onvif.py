"""Minimal ONVIF client (raw SOAP + WS-UsernameToken digest).

Only what we need: capabilities, profiles, RTSP URI, PTZ move/stop/home/preset.
Kept dependency-free on purpose - the big ONVIF libraries are heavy and brittle.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
import xml.etree.ElementTree as ET

from xml.sax.saxutils import escape

import requests

NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
NS_DEV = "http://www.onvif.org/ver10/device/wsdl"
NS_MEDIA = "http://www.onvif.org/ver10/media/wsdl"
NS_PTZ = "http://www.onvif.org/ver20/ptz/wsdl"
NS_SCHEMA = "http://www.onvif.org/ver10/schema"


class OnvifError(RuntimeError):
    pass


class Onvif:
    def __init__(self, host: str, port: int = 80, user: str | None = None, password: str | None = None, timeout: float = 5.0):
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.timeout = timeout
        self.device_url = f"http://{host}:{port}/onvif/device_service"
        self.media_url: str | None = None
        self.ptz_url: str | None = None
        self._profile: str | None = None

    # ---- SOAP plumbing -------------------------------------------------
    def _security(self) -> str:
        if not self.user:
            return ""
        nonce = os.urandom(16)
        created = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + (self.password or "").encode()).digest()).decode()
        return (
            '<Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
            "<UsernameToken>"
            f"<Username>{escape(self.user)}</Username>"
            '<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
            f"{digest}</Password>"
            '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
            f"{base64.b64encode(nonce).decode()}</Nonce>"
            f'<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>'
            "</UsernameToken></Security>"
        )

    def _call(self, url: str, body: str) -> ET.Element:
        envelope = (
            f'<s:Envelope xmlns:s="{NS_SOAP}" xmlns:tds="{NS_DEV}" xmlns:trt="{NS_MEDIA}" '
            f'xmlns:tptz="{NS_PTZ}" xmlns:tt="{NS_SCHEMA}">'
            f"<s:Header>{self._security()}</s:Header><s:Body>{body}</s:Body></s:Envelope>"
        )
        r = requests.post(
            url,
            data=envelope.encode(),
            headers={"Content-Type": "application/soap+xml; charset=utf-8"},
            timeout=self.timeout,
        )
        root = ET.fromstring(r.content) if r.content else None
        if r.status_code != 200 or root is None:
            reason = root.findtext(".//{*}Reason/{*}Text") if root is not None else None
            raise OnvifError(f"{url}: HTTP {r.status_code} {reason or r.text[:200]}")
        return root

    # ---- Discovery -----------------------------------------------------
    def connect(self) -> "Onvif":
        root = self._call(self.device_url, "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>")
        self.media_url = root.findtext(".//{*}Media/{*}XAddr")
        self.ptz_url = root.findtext(".//{*}PTZ/{*}XAddr")
        if not self.media_url:
            raise OnvifError("camera did not report a Media service")
        return self

    def device_info(self) -> dict[str, str]:
        root = self._call(self.device_url, "<tds:GetDeviceInformation/>")
        resp = root.find(".//{*}GetDeviceInformationResponse")
        return {child.tag.split("}")[1]: (child.text or "") for child in (resp if resp is not None else [])}

    def profiles(self) -> list[dict[str, str]]:
        root = self._call(self.media_url, "<trt:GetProfiles/>")
        out = []
        for p in root.iter():
            if p.tag.endswith("}Profiles"):
                res = p.find(".//{*}VideoEncoderConfiguration/{*}Resolution")
                out.append({
                    "token": p.get("token", ""),
                    "name": p.findtext("{*}Name") or "",
                    "resolution": f"{res.findtext('{*}Width')}x{res.findtext('{*}Height')}" if res is not None else "?",
                    "ptz": "yes" if p.find("{*}PTZConfiguration") is not None else "no",
                })
        return out

    def stream_uri(self, token: str) -> str:
        body = (
            "<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream>"
            "<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup>"
            f"<trt:ProfileToken>{escape(token)}</trt:ProfileToken></trt:GetStreamUri>"
        )
        return self._call(self.media_url, body).findtext(".//{*}Uri") or ""

    @property
    def profile(self) -> str:
        if self._profile is None:
            profs = self.profiles()
            if not profs:
                raise OnvifError("no media profiles")
            with_ptz = [p for p in profs if p["ptz"] == "yes"]
            self._profile = (with_ptz or profs)[0]["token"]
        return self._profile

    # ---- PTZ -----------------------------------------------------------
    def _ptz(self) -> str:
        if not self.ptz_url:
            raise OnvifError("camera did not report a PTZ service")
        return self.ptz_url

    def move(self, pan: float, tilt: float, zoom: float = 0.0) -> None:
        """Continuous move, velocities in [-1, 1]."""
        body = (
            f"<tptz:ContinuousMove><tptz:ProfileToken>{self.profile}</tptz:ProfileToken><tptz:Velocity>"
            f'<tt:PanTilt x="{pan:.3f}" y="{tilt:.3f}"/><tt:Zoom x="{zoom:.3f}"/>'
            "</tptz:Velocity></tptz:ContinuousMove>"
        )
        self._call(self._ptz(), body)

    def stop(self) -> None:
        body = (
            f"<tptz:Stop><tptz:ProfileToken>{self.profile}</tptz:ProfileToken>"
            "<tptz:PanTilt>true</tptz:PanTilt><tptz:Zoom>true</tptz:Zoom></tptz:Stop>"
        )
        self._call(self._ptz(), body)

    def goto_home(self) -> None:
        self._call(self._ptz(), f"<tptz:GotoHomePosition><tptz:ProfileToken>{self.profile}</tptz:ProfileToken></tptz:GotoHomePosition>")

    def goto_preset(self, preset: str) -> None:
        body = (
            f"<tptz:GotoPreset><tptz:ProfileToken>{self.profile}</tptz:ProfileToken>"
            f"<tptz:PresetToken>{preset}</tptz:PresetToken></tptz:GotoPreset>"
        )
        self._call(self._ptz(), body)

    def presets(self) -> list[tuple[str, str]]:
        root = self._call(self._ptz(), f"<tptz:GetPresets><tptz:ProfileToken>{self.profile}</tptz:ProfileToken></tptz:GetPresets>")
        return [(p.get("token", ""), p.findtext("{*}Name") or "") for p in root.iter() if p.tag.endswith("}Preset")]
