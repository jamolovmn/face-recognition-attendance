"""Find out what a camera supports: ONVIF, RTSP URLs, PTZ, presets.

    python -m attendance.probe 192.168.1.50 --user admin --password secret
    python -m attendance.probe 192.168.1.50 --user admin --password secret --ptz-test
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import quote, urlsplit, urlunsplit

import cv2

from .onvif import Onvif, OnvifError

COMMON_ONVIF_PORTS = [80, 8899, 8000, 2020, 5000, 6688, 8080]


def with_credentials(uri: str, user: str | None, password: str | None) -> str:
    if not user:
        return uri
    parts = urlsplit(uri)
    netloc = f"{quote(user, safe='')}:{quote(password or '', safe='')}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


def try_rtsp(uri: str, snapshot: str) -> bool:
    cap = cv2.VideoCapture(uri, cv2.CAP_FFMPEG)
    ok, frame = cap.read() if cap.isOpened() else (False, None)
    cap.release()
    if ok:
        cv2.imwrite(snapshot, frame)
        print(f"    OK  {frame.shape[1]}x{frame.shape[0]}  snapshot -> {snapshot}")
    else:
        print("    FAILED to read a frame")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host")
    ap.add_argument("--port", type=int, help="ONVIF port (default: try common ports)")
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--rtsp-port", type=int, help="RTSP port to use instead of the one the camera reports (tunnels)")
    ap.add_argument("--ptz-test", action="store_true", help="pan right, then left, then go home")
    args = ap.parse_args()

    cam = None
    for port in [args.port] if args.port else COMMON_ONVIF_PORTS:
        print(f"ONVIF {args.host}:{port} ...", end=" ", flush=True)
        try:
            cam = Onvif(args.host, port, args.user, args.password, timeout=4).connect()
            print("found")
            break
        except (OnvifError, OSError, Exception) as e:  # noqa: BLE001
            print(type(e).__name__, str(e)[:80])
            cam = None
    if cam is None:
        print("\nNo ONVIF service found. Enable ONVIF in the camera app / web UI, or check user & password.")
        print("Without ONVIF you can still use RTSP (no PTZ). Common URLs to try in VLC:")
        for path in ("/ch0_0.h264", "/live/ch00_0", "/onvif1", "/stream1", "/h264_stream", "/11"):
            print(f"  rtsp://USER:PASS@{args.host}:554{path}")
        return 1

    try:
        print("\nDevice:", cam.device_info())
    except OnvifError as e:
        print("\nDevice info unavailable:", e)

    print(f"\nPTZ service: {cam.ptz_url or 'NOT supported'}")
    print("\nProfiles:")
    for i, p in enumerate(cam.profiles()):
        print(f"  [{p['token']}] {p['name']}  {p['resolution']}  ptz={p['ptz']}")
        try:
            uri = cam.stream_uri(p["token"])
        except OnvifError as e:
            print("    stream uri error:", e)
            continue
        print(f"    RTSP: {uri}")
        parts = urlsplit(uri)
        if parts.hostname != args.host or args.rtsp_port:
            uri = urlunsplit(parts._replace(netloc=f"{args.host}:{args.rtsp_port or parts.port or 554}"))
            print(f"    via:  {uri}")
        out_dir = os.path.dirname(os.environ.get("GALLERY_PATH", "data/gallery.npz"))
        out_dir = out_dir if os.path.isdir(out_dir) else "."
        try_rtsp(with_credentials(uri, args.user, args.password), os.path.join(out_dir, f"probe_{args.host}_{i}.jpg"))

    if cam.ptz_url:
        try:
            print("\nPresets:", cam.presets() or "none")
        except OnvifError as e:
            print("\nPresets unavailable:", e)
        if args.ptz_test:
            print("\nPTZ test: right 1s, left 1s, home")
            for pan in (0.5, -0.5):
                cam.move(pan, 0)
                time.sleep(1)
                cam.stop()
                time.sleep(1)
            cam.goto_home()
            print("PTZ OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
