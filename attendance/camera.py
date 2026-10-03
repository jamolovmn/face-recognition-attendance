"""RTSP reader that keeps only the latest frame and can idle cheaply.

Decoding a 1080p H.264 stream is the single biggest constant CPU cost, so the
reader has two modes:

* idle      - only keyframes are decoded (typically 1 per 1-4 s); every other
              packet is dropped before it reaches the decoder.
* full      - every frame is decoded (needed for P-frames), but conversion to a
              numpy image happens lazily, only for the frames actually analysed.

The connection stays open in both modes, so switching to full mode costs at most
one keyframe interval instead of an RTSP reconnect.
"""
from __future__ import annotations

import logging
import threading
import time

import av
import numpy as np

log = logging.getLogger(__name__)


class LatestFrameReader:
    def __init__(self, name: str, url: str, full: bool = True):
        self.name = name
        self.url = url
        self._lock = threading.Lock()
        self._frame: av.VideoFrame | None = None
        self._seq = 0
        self._converted: tuple[int, np.ndarray] | None = None
        self._full = threading.Event()
        if full:
            self._full.set()
        self._paused = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"rtsp-{name}", daemon=True)
        self.decoded = 0  # statistics: frames actually decoded

    # ---- control ---------------------------------------------------------
    def start(self) -> "LatestFrameReader":
        self._thread.start()
        return self

    def set_full(self, full: bool) -> None:
        if full and not self._full.is_set():
            self._full.set()
        elif not full and self._full.is_set():
            self._full.clear()

    def pause(self) -> None:
        """Close the connection (outside working hours)."""
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    # ---- consumer ----------------------------------------------------------
    def read(self) -> tuple[int, np.ndarray | None]:
        """Return (sequence number, BGR image). Sequence grows with every new frame."""
        with self._lock:
            seq, frame = self._seq, self._frame
            cached = self._converted
        if frame is None:
            return seq, None
        if cached is not None and cached[0] == seq:
            return cached
        img = frame.to_ndarray(format="bgr24")
        with self._lock:
            self._converted = (seq, img)
        return seq, img

    # ---- worker ------------------------------------------------------------
    def _open(self):
        options = {"rtsp_transport": "tcp"} if self.url.startswith("rtsp") else {}
        return av.open(self.url, options=options, timeout=(10.0, 10.0))

    def _run(self) -> None:
        backoff = 1.0
        while True:
            if self._paused.is_set():
                time.sleep(2)
                continue
            try:
                container = self._open()
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] cannot open stream (%s), retry in %.0fs", self.name, e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            log.info("[%s] stream connected", self.name)
            backoff = 1.0
            try:
                self._pump(container)
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] stream error: %s - reconnecting", self.name, e)
            finally:
                container.close()
            time.sleep(1)

    def _pump(self, container) -> None:
        stream = container.streams.video[0]
        stream.thread_count = 1  # one decode thread per camera keeps CPU predictable
        await_key = True
        was_full = self._full.is_set()
        for packet in container.demux(stream):
            if self._paused.is_set():
                log.info("[%s] paused (outside working hours)", self.name)
                return
            if packet.size == 0:
                continue
            full = self._full.is_set()
            if full and not was_full:
                await_key = True  # P-frames after a gap reference frames we never decoded
            was_full = full
            if not full and not packet.is_keyframe:
                continue
            if await_key:
                if not packet.is_keyframe:
                    continue
                await_key = False
            for frame in packet.decode():
                self.decoded += 1
                with self._lock:
                    self._frame = frame
                    self._seq += 1
        log.warning("[%s] stream ended", self.name)
