"""Collect photos of unknown people automatically and learn them once they are named.

    New faces/                    <- the service fills this
      person-1104-093012/         up to COLLECT_PER_PERSON clear, frontal, varied photos
    People/                       <- you move a folder here and rename it to the person's name
      Ali Valiyev/

Both folders live in the bot user's Nextcloud files (shared with whoever names
people) and are mirrored to every camera node, so a backup PC knows the same
people and the same half-collected strangers.
"""
from __future__ import annotations

import json
import logging
import math
import os
import queue
import threading
import time
from datetime import datetime

import cv2
import numpy as np

from .config import Config
from .enroll import IMAGE_EXT, build_gallery, enroll_engine, imread_unicode
from .faces import FaceEngine, crop_snapshot
from .webdav import WebDav

log = logging.getLogger(__name__)


def face_quality(frame: np.ndarray, row: np.ndarray, min_px: int, min_sharpness: float) -> float | None:
    """Sharpness of a clear, frontal, fully visible face; None if the photo is not good enough."""
    x, y, w, h = (float(v) for v in row[:4])
    H, W = frame.shape[:2]
    if min(w, h) < min_px or row[14] < 0.9:
        return None
    if x < 0 or y < 0 or x + w > W or y + h > H:
        return None  # cut off by the frame edge
    (rx, ry), (lx, ly), (nx, _) = row[4:6], row[6:8], row[8:10]
    eye_dist = math.hypot(lx - rx, ly - ry)
    if eye_dist < 0.3 * w:
        return None  # profile
    if abs(nx - (rx + lx) / 2) > 0.2 * eye_dist:
        return None  # head turned
    if abs(math.degrees(math.atan2(ly - ry, lx - rx))) > 20:
        return None  # head tilted
    face = cv2.cvtColor(frame[int(y):int(y + h), int(x):int(x + w)], cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(cv2.resize(face, (112, 112)), cv2.CV_64F).var())
    return sharpness if sharpness >= min_sharpness else None


class FolderMirror:
    """Keeps local/<folder>/<photo> identical to the same layout in Nextcloud."""

    def __init__(self, dav: WebDav, remote: str, local: str):
        self.dav, self.remote, self.local = dav, remote.strip("/"), local
        self.lock = threading.Lock()  # held while the local copy is being changed
        self._etag: str | None = None
        self._index_path = os.path.join(local, ".mirror.json")
        os.makedirs(local, exist_ok=True)
        try:
            with open(self._index_path, encoding="utf-8") as f:
                self._index: dict[str, str] = json.load(f)
        except (OSError, ValueError):
            self._index = {}

    def _save_index(self) -> None:
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f)

    def pull(self) -> bool:
        """Download what changed in Nextcloud; True if the local copy changed."""
        listing = self.dav.list(self.remote)
        if listing is None:
            self.dav.mkdirs(self.remote)
            return False
        etag, entries = listing
        if etag == self._etag:
            return False  # Nextcloud folder etags change when anything inside changes
        with self.lock:
            changed = False
            seen: set[str] = set()
            for d in entries:
                if not d.is_dir or d.name.startswith("."):
                    continue
                sub = self.dav.list(f"{self.remote}/{d.name}")
                for f in (sub[1] if sub else []):
                    if f.is_dir or not f.name.lower().endswith(IMAGE_EXT):
                        continue
                    rel = f"{d.name}/{f.name}"
                    seen.add(rel)
                    path = os.path.join(self.local, d.name, f.name)
                    if self._index.get(rel) != f.etag or not os.path.exists(path):
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "wb") as out:
                            out.write(self.dav.get(f"{self.remote}/{rel}"))
                        self._index[rel] = f.etag
                        changed = True
            for folder in os.listdir(self.local):
                fdir = os.path.join(self.local, folder)
                if not os.path.isdir(fdir):
                    continue
                for name in os.listdir(fdir):
                    if f"{folder}/{name}" not in seen:
                        os.remove(os.path.join(fdir, name))
                        changed = True
                if not os.listdir(fdir):
                    os.rmdir(fdir)
            self._index = {k: v for k, v in self._index.items() if k in seen}
            self._save_index()
            self._etag = etag
        return changed

    def add(self, folder: str, name: str, data: bytes) -> None:
        """Upload a new photo and keep the local copy in step (no re-download)."""
        with self.lock:
            self.dav.mkdirs(f"{self.remote}/{folder}")
            etag = self.dav.put(f"{self.remote}/{folder}/{name}", data)
            path = os.path.join(self.local, folder, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as out:
                out.write(data)
            self._index[f"{folder}/{name}"] = etag
            self._save_index()


class FaceCollector:
    """Groups unknown faces into people and keeps the best varied photos of each."""

    SAME_PERSON = 0.50   # similarity to any photo of a group -> same person
    NEAR_DUPLICATE = 0.93  # almost the same photo as one we already have
    MIN_GAP_SEC = 2.0    # between two photos of the same person

    def __init__(self, cfg: Config, mirror: FolderMirror | None, local_dir: str):
        self.cfg, self.mirror, self.local_dir = cfg, mirror, local_dir
        self._lock = threading.Lock()
        self._groups: dict[str, list[np.ndarray]] = {}
        self._last_add: dict[str, float] = {}
        self._cache: dict[tuple[str, float], np.ndarray | None] = {}
        self._q: queue.Queue = queue.Queue(maxsize=100)
        os.makedirs(local_dir, exist_ok=True)
        threading.Thread(target=self._writer, name="collector", daemon=True).start()

    def offer(self, frame: np.ndarray, row: np.ndarray, embedding: np.ndarray) -> None:
        """Called by camera threads for every unknown face (cheap when the photo is rejected)."""
        if face_quality(frame, row, self.cfg.collect_min_face_px, self.cfg.collect_min_sharpness) is None:
            return
        now = time.monotonic()
        with self._lock:
            best, best_sim = None, 0.0
            for folder, embs in self._groups.items():
                sim = float(np.max(np.stack(embs) @ embedding))
                if sim > best_sim:
                    best, best_sim = folder, sim
            if best is not None and best_sim >= self.SAME_PERSON:
                embs = self._groups[best]
                if len(embs) >= self.cfg.collect_per_person or best_sim >= self.NEAR_DUPLICATE \
                        or now - self._last_add.get(best, 0.0) < self.MIN_GAP_SEC:
                    return
                folder = best
            else:
                folder = datetime.now().strftime("person-%m%d-%H%M%S")
                while folder in self._groups:
                    folder += "x"
                log.info("new person seen -> %s", folder)
            self._groups.setdefault(folder, []).append(embedding)
            self._last_add[folder] = now
            count = len(self._groups[folder])
        box = tuple(int(v) for v in row[:4])
        jpeg = crop_snapshot(frame, box, pad=0.5, max_side=480)
        name = datetime.now().strftime("%Y%m%d-%H%M%S-") + f"{count:02d}.jpg"
        try:
            self._q.put_nowait((folder, name, jpeg))
        except queue.Full:
            pass

    def _writer(self) -> None:
        while True:
            folder, name, jpeg = self._q.get()
            try:
                if self.mirror is not None:
                    self.mirror.add(folder, name, jpeg)
                else:
                    os.makedirs(os.path.join(self.local_dir, folder), exist_ok=True)
                    with open(os.path.join(self.local_dir, folder, name), "wb") as f:
                        f.write(jpeg)
            except Exception as e:  # noqa: BLE001
                log.warning("cannot save collected photo %s/%s: %s", folder, name, e)

    def reload(self, engine: FaceEngine) -> None:
        """Rebuild the groups from the photos on disk (after renames, merges or deletions)."""
        groups: dict[str, list[np.ndarray]] = {}
        cache: dict[tuple[str, float], np.ndarray | None] = {}
        for folder in sorted(os.listdir(self.local_dir)):
            fdir = os.path.join(self.local_dir, folder)
            if not os.path.isdir(fdir) or folder.startswith("."):
                continue
            for name in os.listdir(fdir):
                path = os.path.join(fdir, name)
                key = (path, os.path.getmtime(path))
                if key not in self._cache:
                    img = imread_unicode(path)
                    rows = engine.detect(img) if img is not None else []
                    self._cache[key] = engine.embed(img, max(rows, key=lambda r: r[2] * r[3])) if rows else None
                cache[key] = self._cache[key]
                if cache[key] is not None:
                    groups.setdefault(folder, []).append(cache[key])
        with self._lock:
            self._groups = groups
        self._cache = cache
        log.info("collecting: %d unnamed people, %d photos", len(groups), sum(map(len, groups.values())))


class FaceSync(threading.Thread):
    """Every SYNC_SEC: pull named people -> rebuild the gallery; pull new faces -> regroup."""

    def __init__(self, cfg: Config, dav: WebDav, gallery_holder, collector: FaceCollector | None,
                 new_mirror: FolderMirror | None):
        super().__init__(name="face-sync", daemon=True)
        self.cfg, self.gallery_holder, self.collector = cfg, gallery_holder, collector
        self.people = FolderMirror(dav, cfg.nc_people_dir, cfg.faces_dir) if cfg.nc_people_dir else None
        self.new_mirror = new_mirror

    def run(self) -> None:
        engine = enroll_engine(self.cfg.models_dir)
        first = True
        while True:
            try:
                if self.people is not None and (self.people.pull() or first):
                    gallery = build_gallery(self.cfg.faces_dir, engine, log)
                    gallery.save(self.cfg.gallery_path)
                    self.gallery_holder.maybe_reload()
                    log.info("people from Nextcloud: %d (%d photos)", len(set(gallery.names)), len(gallery.names))
                if self.collector is not None and ((self.new_mirror and self.new_mirror.pull()) or first):
                    self.collector.reload(engine)
                first = False
            except Exception as e:  # noqa: BLE001
                log.warning("face sync with Nextcloud failed: %s", e)
            time.sleep(self.cfg.sync_sec)
