"""RTSP reader that always keeps only the latest frame (no growing lag)."""
from __future__ import annotations

import logging
import os
import threading
import time

import cv2
import numpy as np

# TCP is far more reliable than UDP for RTSP over Wi-Fi / VPN links.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")

log = logging.getLogger(__name__)


class LatestFrameReader:
    def __init__(self, name: str, url: str):
        self.name = name
        self.url = url
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"rtsp-{name}", daemon=True)

    def start(self) -> "LatestFrameReader":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def read(self) -> tuple[int, np.ndarray | None]:
        """Return (sequence number, frame). Sequence grows with every new frame."""
        with self._lock:
            return self._seq, self._frame

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                log.warning("[%s] cannot open stream, retry in %.0fs", self.name, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            log.info("[%s] stream connected", self.name)
            backoff = 1.0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    log.warning("[%s] stream lost, reconnecting", self.name)
                    break
                with self._lock:
                    self._frame = frame
                    self._seq += 1
            cap.release()
            time.sleep(1)
