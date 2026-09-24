"""Build the gallery from photos.

Layout:  faces/<Person Name>/*.jpg   (5-10 photos per person, different angles/light)

    python -m attendance.enroll
"""
from __future__ import annotations

import logging
import os
import sys

import cv2
import numpy as np

from . import config as cfgmod
from .faces import FaceEngine
from .gallery import Gallery

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def imread_unicode(path: str):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = cfgmod.load()
    engine = FaceEngine(cfg.models_dir, detect_width=1280, score=0.7, min_face_px=30)

    if not os.path.isdir(cfg.faces_dir):
        print(f"faces directory not found: {cfg.faces_dir}", file=sys.stderr)
        return 1

    names: list[str] = []
    embs: list[np.ndarray] = []
    for person in sorted(os.listdir(cfg.faces_dir)):
        pdir = os.path.join(cfg.faces_dir, person)
        if not os.path.isdir(pdir) or person.startswith("."):
            continue
        count = 0
        for fname in sorted(os.listdir(pdir)):
            if not fname.lower().endswith(IMAGE_EXT):
                continue
            path = os.path.join(pdir, fname)
            img = imread_unicode(path)
            if img is None:
                logging.warning("cannot read %s", path)
                continue
            rows = engine.detect(img)
            if not rows:
                logging.warning("no face found: %s", path)
                continue
            if len(rows) > 1:
                logging.info("%d faces in %s - using the largest", len(rows), path)
            row = max(rows, key=lambda r: r[2] * r[3])
            names.append(person)
            embs.append(engine.embed(img, row))
            count += 1
        level = logging.INFO if count >= 3 else logging.WARNING
        logging.log(level, "%-30s %d photo(s)%s", person, count, "" if count >= 3 else "  <- add more photos")

    if not names:
        print("no faces enrolled", file=sys.stderr)
        return 1
    Gallery(names, np.stack(embs)).save(cfg.gallery_path)
    print(f"saved {len(names)} embeddings for {len(set(names))} people -> {cfg.gallery_path}")
    print("restart the service (or it reloads automatically within a minute)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
