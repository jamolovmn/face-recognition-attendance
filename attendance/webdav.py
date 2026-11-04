"""Tiny WebDAV client for the bot user's Nextcloud files (folders of face photos)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

import requests

from .config import Config

PROPFIND = (
    '<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
    "<d:getetag/><d:resourcetype/></d:prop></d:propfind>"
)


@dataclass
class Entry:
    name: str
    is_dir: bool
    etag: str


class WebDav:
    def __init__(self, cfg: Config):
        self.base = f"{cfg.nc_url}/remote.php/dav/files/{quote(cfg.nc_user)}"
        self.session = requests.Session()
        self.session.auth = (cfg.nc_user, cfg.nc_app_password)
        self.session.verify = cfg.nc_verify_tls

    def _url(self, path: str) -> str:
        return self.base + "/" + quote(path.strip("/"))

    def list(self, path: str) -> tuple[str, list[Entry]] | None:
        """(folder etag, children) or None if the folder does not exist."""
        r = self.session.request("PROPFIND", self._url(path), data=PROPFIND, headers={"Depth": "1"}, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        own = urlsplit(self._url(path)).path.rstrip("/")
        folder_etag, children = "", []
        for resp in ET.fromstring(r.content).iter("{DAV:}response"):
            href = unquote(urlsplit(resp.findtext("{DAV:}href") or "").path).rstrip("/")
            etag = (resp.findtext(".//{DAV:}getetag") or "").strip('"')
            is_dir = resp.find(".//{DAV:}resourcetype/{DAV:}collection") is not None
            if href == unquote(own):
                folder_etag = etag
            else:
                children.append(Entry(href.rsplit("/", 1)[-1], is_dir, etag))
        return folder_etag, children

    def mkdirs(self, path: str) -> None:
        parts = [p for p in path.strip("/").split("/") if p]
        for i in range(1, len(parts) + 1):
            r = self.session.request("MKCOL", self._url("/".join(parts[:i])), timeout=30)
            if r.status_code not in (201, 405):  # 405 = already exists
                r.raise_for_status()

    def get(self, path: str) -> bytes:
        r = self.session.get(self._url(path), timeout=60)
        r.raise_for_status()
        return r.content

    def put(self, path: str, data: bytes) -> str:
        r = self.session.put(self._url(path), data=data, timeout=60)
        r.raise_for_status()
        return (r.headers.get("OC-ETag") or r.headers.get("ETag") or "").strip('"')
