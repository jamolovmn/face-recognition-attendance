"""Send attendance events to the Nextcloud 'faceattendance' app.

Events that cannot be delivered (Nextcloud down, network gone) are spooled to
disk and retried, so nothing is lost.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import queue
import threading
import time
import uuid

import requests

from .config import Config

log = logging.getLogger(__name__)

API_PATH = "/ocs/v2.php/apps/faceattendance/api/v1/events"


class NextcloudSink:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.enabled = bool(cfg.nc_url and cfg.nc_user and cfg.nc_app_password)
        if not self.enabled:
            log.warning("NC_URL / NC_USER / NC_APP_PASSWORD not set - events are only logged")
        os.makedirs(cfg.spool_dir, exist_ok=True)
        self._q: queue.Queue = queue.Queue()
        self._session = requests.Session()
        self._session.auth = (cfg.nc_user, cfg.nc_app_password)
        self._session.headers.update({"OCS-APIRequest": "true", "Accept": "application/json"})
        self._session.verify = cfg.nc_verify_tls
        threading.Thread(target=self._worker, name="nextcloud-sink", daemon=True).start()

    def send(self, *, person: str | None, camera: str, room: str, score: float, ts: float, snapshot: bytes | None) -> None:
        event = {
            "uid": uuid.uuid4().hex,
            "person": person,
            "camera": camera,
            "room": room,
            "score": round(score, 4),
            "ts": int(ts),
            "snapshot": base64.b64encode(snapshot).decode() if snapshot else None,
        }
        log.info("EVENT %s | %s | %s | score=%.2f", room, person or "UNKNOWN", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)), score)
        self._q.put(event)

    def _post(self, event: dict) -> bool:
        if not self.enabled:
            return True
        try:
            r = self._session.post(self.cfg.nc_url + API_PATH, json=event, timeout=15)
        except requests.RequestException as e:
            log.warning("Nextcloud unreachable: %s", e)
            return False
        if r.status_code in (200, 201):
            return True
        if 400 <= r.status_code < 500 and r.status_code not in (401, 403, 404, 429):
            log.error("Nextcloud rejected event (%s): %s - dropping", r.status_code, r.text[:300])
            return True  # retrying a malformed event would never succeed
        log.warning("Nextcloud error %s: %s", r.status_code, r.text[:200])
        return False

    def _spool(self, event: dict) -> None:
        path = os.path.join(self.cfg.spool_dir, f"{event['ts']}_{event['uid']}.json")
        with open(path, "w") as f:
            json.dump(event, f)

    def _flush_spool(self) -> None:
        for name in sorted(os.listdir(self.cfg.spool_dir)):
            path = os.path.join(self.cfg.spool_dir, name)
            try:
                with open(path) as f:
                    event = json.load(f)
            except (OSError, ValueError):
                os.remove(path)
                continue
            if not self._post(event):
                return
            os.remove(path)

    def _worker(self) -> None:
        last_flush = 0.0
        while True:
            try:
                event = self._q.get(timeout=30)
            except queue.Empty:
                event = None
            if event is not None and not self._post(event):
                self._spool(event)
            if time.monotonic() - last_flush > 60:
                last_flush = time.monotonic()
                self._flush_spool()
