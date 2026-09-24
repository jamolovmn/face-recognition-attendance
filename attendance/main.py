"""Entry point: one worker thread per camera.

    python -m attendance.main
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import config as cfgmod
from .camera import LatestFrameReader
from .config import CameraConfig, Config
from .faces import FaceEngine, crop_snapshot
from .gallery import Gallery
from .ptz import PtzTracker
from .sink import NextcloudSink

log = logging.getLogger("attendance")


class GalleryHolder:
    """Shares the gallery between cameras and hot-reloads it after re-enrolment."""

    def __init__(self, path: str):
        self.path = path
        self._mtime = self._stat()
        self.gallery = Gallery.load(path)

    def _stat(self) -> float:
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def maybe_reload(self) -> None:
        m = self._stat()
        if m and m != self._mtime:
            self._mtime = m
            self.gallery = Gallery.load(self.path)


@dataclass
class UnknownCluster:
    embedding: np.ndarray
    hits: deque = field(default_factory=deque)
    last_seen: float = 0.0
    last_event: float = 0.0


class Cooldowns:
    """One event per person per room per COOLDOWN_MIN, shared by all cameras."""

    def __init__(self):
        self._last: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def active(self, key: tuple[str, str], seconds: float, now: float) -> bool:
        with self._lock:
            return now - self._last.get(key, -1e12) < seconds

    def mark(self, key: tuple[str, str], now: float) -> None:
        with self._lock:
            self._last[key] = now


class CameraWorker(threading.Thread):
    UNKNOWN_SAME_PERSON = 0.50  # similarity above which two unknown faces are "the same stranger"

    def __init__(self, cam: CameraConfig, cfg: Config, gallery: GalleryHolder, sink: NextcloudSink, cooldowns: Cooldowns):
        super().__init__(name=f"cam-{cam.id}", daemon=True)
        self.cam, self.cfg = cam, cfg
        self.gallery, self.sink, self.cooldowns = gallery, sink, cooldowns
        self.reader = LatestFrameReader(cam.id, cam.rtsp)
        self.ptz = PtzTracker(cam, cfg) if cam.ptz and cam.onvif_host else None
        self.hits: dict[str, deque] = defaultdict(deque)
        self.unknowns: list[UnknownCluster] = []
        self._prev_small: np.ndarray | None = None
        self._last_face_at = 0.0

    # -------------------------------------------------------------------
    def _has_motion(self, frame: np.ndarray) -> bool:
        small = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
        small = cv2.GaussianBlur(small, (5, 5), 0)
        prev, self._prev_small = self._prev_small, small
        if prev is None:
            return True
        changed = np.count_nonzero(cv2.absdiff(prev, small) > 25) / small.size
        return changed >= self.cfg.motion_threshold

    def _confirmed(self, q: deque, now: float, needed: int) -> bool:
        q.append(now)
        while q and now - q[0] > self.cfg.confirm_window_sec:
            q.popleft()
        return len(q) >= needed

    def _handle_unknown(self, frame: np.ndarray, face, now: float) -> None:
        ttl = self.cfg.unknown_cooldown_min * 60
        self.unknowns = [u for u in self.unknowns if now - u.last_seen < ttl]
        best, best_sim = None, 0.0
        for u in self.unknowns:
            sim = float(u.embedding @ face.embedding)
            if sim > best_sim:
                best, best_sim = u, sim
        if best is None or best_sim < self.UNKNOWN_SAME_PERSON:
            best = UnknownCluster(embedding=face.embedding)
            self.unknowns.append(best)
        best.last_seen = now
        # Strangers need twice as many hits: we would rather miss one than spam.
        if self._confirmed(best.hits, now, self.cfg.confirm_hits * 2) and now - best.last_event > ttl:
            best.last_event = now
            best.hits.clear()
            self.sink.send(
                person=None, camera=self.cam.id, room=self.cam.room, score=0.0, ts=time.time(),
                snapshot=crop_snapshot(frame, face.box) if self.cfg.snapshot else None,
            )

    def _process(self, frame: np.ndarray, engine: FaceEngine) -> None:
        now = time.monotonic()
        faces = engine.analyze(frame)
        gallery = self.gallery.gallery
        cooldown = self.cfg.cooldown_min * 60
        pending: set[int] = set()

        for i, face in enumerate(faces):
            name, score = gallery.match(face.embedding)
            if name is not None and score >= self.cfg.match_threshold:
                key = (name, self.cam.room)
                if self.cooldowns.active(key, cooldown, now):
                    continue  # already logged recently - PTZ can move on
                pending.add(i)
                if self._confirmed(self.hits[name], now, self.cfg.confirm_hits):
                    self.cooldowns.mark(key, now)
                    self.hits[name].clear()
                    self.sink.send(
                        person=name, camera=self.cam.id, room=self.cam.room, score=score, ts=time.time(),
                        snapshot=crop_snapshot(frame, face.box) if self.cfg.snapshot else None,
                    )
            else:
                pending.add(i)
                # Grey zone (close to threshold) is ignored: likely a known person at a bad angle.
                if self.cfg.unknown_events and score < self.cfg.match_threshold - 0.1:
                    self._handle_unknown(frame, face, now)

        if faces:
            self._last_face_at = now
        if self.ptz:
            h, w = frame.shape[:2]
            self.ptz.update(faces, w, h, pending)

    def run(self) -> None:
        engine = FaceEngine(self.cfg.models_dir, self.cfg.detect_width, self.cfg.detect_score, self.cfg.min_face_px)
        self.reader.start()
        period = 1.0 / max(self.cfg.process_fps, 0.1)
        last_seq = -1
        log.info("[%s] started (room=%s, ptz=%s)", self.cam.id, self.cam.room, bool(self.ptz))
        while True:
            t0 = time.monotonic()
            seq, frame = self.reader.read()
            if frame is not None and seq != last_seq:
                last_seq = seq
                recent_face = t0 - self._last_face_at < 3.0
                if not self.cfg.motion_gate or self._has_motion(frame) or recent_face:
                    try:
                        self._process(frame, engine)
                    except Exception:  # noqa: BLE001
                        log.exception("[%s] processing error", self.cam.id)
            time.sleep(max(0.0, period - (time.monotonic() - t0)))


def main() -> None:
    cfg = cfgmod.load()
    logging.basicConfig(level=cfg.log_level.upper(), format="%(asctime)s %(levelname)-7s %(threadName)s: %(message)s")
    if not cfg.cameras:
        raise SystemExit("no cameras configured - set CAMERAS and CAM_<ID>_RTSP in .env")
    cv2.setNumThreads(max(1, (os.cpu_count() or 2) // max(1, len(cfg.cameras))))

    gallery = GalleryHolder(cfg.gallery_path)
    sink = NextcloudSink(cfg)
    cooldowns = Cooldowns()
    for cam in cfg.cameras:
        CameraWorker(cam, cfg, gallery, sink, cooldowns).start()

    while True:
        time.sleep(60)
        gallery.maybe_reload()


if __name__ == "__main__":
    main()
