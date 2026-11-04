"""Known-people gallery: several embeddings per person, matched by cosine similarity."""
from __future__ import annotations

import logging
import os

import numpy as np

log = logging.getLogger(__name__)


class Gallery:
    def __init__(self, names: list[str], embeddings: np.ndarray):
        self.names = names
        self.embeddings = embeddings  # (N, 128), L2-normalised

    @classmethod
    def load(cls, path: str) -> "Gallery":
        if not os.path.exists(path):
            log.warning("gallery %s not found - everybody will be 'unknown'. Run: python -m attendance.enroll", path)
            return cls([], np.zeros((0, 128), np.float32))
        data = np.load(path, allow_pickle=False)
        names = [str(n) for n in data["names"]]
        log.info("gallery loaded: %d embeddings, %d people", len(names), len(set(names)))
        return cls(names, data["embeddings"].astype(np.float32))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Write next to it and swap, so a running service never loads a half-written file
        tmp = path + ".tmp.npz"
        np.savez(tmp, names=np.array(self.names, dtype=str), embeddings=self.embeddings)
        os.replace(tmp, path)

    def match(self, embedding: np.ndarray) -> tuple[str | None, float]:
        if not self.names:
            return None, 0.0
        sims = self.embeddings @ embedding
        i = int(np.argmax(sims))
        return self.names[i], float(sims[i])
