"""Keep a face centred and zoomed using short ONVIF move pulses.

RTSP has ~0.5-1.5 s latency, so a naive "move while off-centre" loop overshoots
and oscillates. Instead we send a short pulse proportional to the error, stop,
and wait for the picture to settle before judging again.
"""
from __future__ import annotations

import logging
import queue
import threading
import time

from .config import CameraConfig, Config
from .faces import Face
from .onvif import Onvif

log = logging.getLogger(__name__)


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class PtzTracker:
    SETTLE_SEC = 1.2  # wait for the stream to catch up after a move
    MAX_PULSE_SEC = 0.6

    def __init__(self, cam: CameraConfig, cfg: Config):
        self.cam, self.cfg = cam, cfg
        self.onvif = Onvif(cam.onvif_host or "", cam.onvif_port, cam.onvif_user, cam.onvif_pass)
        self._cmds: queue.Queue = queue.Queue(maxsize=1)
        self._busy_until = 0.0
        self._last_face_at = time.monotonic()
        self._at_home = False
        self._ready = False
        threading.Thread(target=self._worker, name=f"ptz-{cam.id}", daemon=True).start()

    # ---- called from the detection loop --------------------------------
    def update(self, faces: list[Face], frame_w: int, frame_h: int, pending: set[int]) -> None:
        """faces: detections this frame; pending: indexes of faces not yet identified."""
        now = time.monotonic()
        if not faces:
            if not self._at_home and now - self._last_face_at > self.cfg.ptz_idle_return_sec:
                self._submit(("home",))
                self._at_home = True
            return

        self._last_face_at = now
        if now < self._busy_until:
            return

        # Prefer faces we still need to identify; among them the biggest (closest).
        candidates = [faces[i] for i in pending] or faces
        target = max(candidates, key=lambda f: f.box[2] * f.box[3])
        cx, cy = target.center
        dx, dy = cx / frame_w - 0.5, cy / frame_h - 0.5
        face_w = target.box[2]

        pan = tilt = zoom = 0.0
        dz = self.cfg.ptz_deadzone
        if abs(dx) > dz:
            pan = _clamp(dx * 2 * self.cfg.ptz_speed)
        if abs(dy) > dz:
            tilt = _clamp(-dy * 2 * self.cfg.ptz_speed)
        centred = pan == 0.0 and tilt == 0.0
        if centred and pending and face_w < self.cfg.ptz_zoom_target_px:
            zoom = 0.4
        elif face_w > self.cfg.ptz_zoom_target_px * 3:
            zoom = -0.4

        if pan or tilt or zoom:
            pulse = min(self.MAX_PULSE_SEC, 0.15 + max(abs(dx), abs(dy)))
            self._submit(("move", pan, tilt, zoom, pulse))
            self._busy_until = now + pulse + self.SETTLE_SEC
            self._at_home = False

    # ---- worker ----------------------------------------------------------
    def _submit(self, cmd: tuple) -> None:
        try:
            self._cmds.put_nowait(cmd)
        except queue.Full:
            pass  # a command is already in flight; drop this one

    def _worker(self) -> None:
        while not self._ready:
            try:
                self.onvif.connect()
                log.info("[%s] ONVIF PTZ ready (profile %s)", self.cam.id, self.onvif.profile)
                self._ready = True
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] ONVIF connect failed: %s (retry in 30s)", self.cam.id, e)
                time.sleep(30)
        self._submit(("home",))
        while True:
            cmd = self._cmds.get()
            try:
                if cmd[0] == "move":
                    _, pan, tilt, zoom, pulse = cmd
                    self.onvif.move(pan, tilt, zoom)
                    time.sleep(pulse)
                    self.onvif.stop()
                elif cmd[0] == "home":
                    log.info("[%s] returning to home position", self.cam.id)
                    if self.cam.home_preset:
                        self.onvif.goto_preset(self.cam.home_preset)
                    else:
                        self.onvif.goto_home()
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] PTZ command %s failed: %s", self.cam.id, cmd[0], e)
