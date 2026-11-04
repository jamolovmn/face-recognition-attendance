"""Active/standby failover between several camera nodes (e.g. two office PCs).

Every node sends a heartbeat to the Nextcloud app; only the lease holder runs the
cameras. The node with the lowest NODE_PRIORITY is preferred: it takes over as
soon as it is up, the others wait until the holder misses LEASE_TTL_SEC.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

from .config import Config

log = logging.getLogger(__name__)

API_PATH = "/ocs/v2.php/apps/faceattendance/api/v1/lease"


class Lease:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._leader = threading.Event()
        if not cfg.failover:
            self._leader.set()
            return
        self._session = requests.Session()
        self._session.auth = (cfg.nc_user, cfg.nc_app_password)
        self._session.headers.update({"OCS-APIRequest": "true", "Accept": "application/json"})
        self._session.verify = cfg.nc_verify_tls
        threading.Thread(target=self._run, name="lease", daemon=True).start()

    def is_leader(self) -> bool:
        return self._leader.is_set()

    def _renew(self) -> dict | None:
        try:
            r = self._session.post(
                self.cfg.nc_url + API_PATH,
                json={"node": self.cfg.node_id, "priority": self.cfg.node_priority, "ttl": int(self.cfg.lease_ttl_sec)},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()["ocs"]["data"]
        except (requests.RequestException, ValueError, KeyError) as e:
            log.warning("lease heartbeat failed: %s", e)
            return None

    def _run(self) -> None:
        log.info("failover on: node=%s priority=%d", self.cfg.node_id, self.cfg.node_priority)
        interval = max(5.0, self.cfg.lease_ttl_sec / 3)
        while True:
            data = self._renew()
            # Nextcloud unreachable: keep the current role. An active node keeps working
            # (events are spooled), a standby node never starts on a guess.
            if data is not None:
                if data["leader"] and not self._leader.is_set():
                    log.info("this node is now ACTIVE")
                    self._leader.set()
                elif not data["leader"] and self._leader.is_set():
                    log.info("node '%s' is active - this node goes to STANDBY", data["holder"])
                    self._leader.clear()
                elif not data["leader"]:
                    log.debug("standby, active node: %s", data["holder"])
            time.sleep(interval)
