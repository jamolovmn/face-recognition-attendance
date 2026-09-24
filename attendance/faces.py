"""Face detection (YuNet) and recognition (SFace) on CPU via OpenCV.

Both models come from the OpenCV Model Zoo and are permissively licensed
(YuNet: MIT, SFace: Apache-2.0), so they are safe for commercial use.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"


@dataclass
class Face:
    box: tuple[int, int, int, int]  # x, y, w, h in full-resolution pixels
    score: float
    embedding: np.ndarray  # L2-normalised, shape (128,)

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2, y + h / 2


class FaceEngine:
    """Not thread-safe: create one instance per camera thread."""

    def __init__(self, models_dir: str, detect_width: int = 1280, score: float = 0.8, min_face_px: int = 40):
        self.detect_width = detect_width
        self.min_face_px = min_face_px
        self.detector = cv2.FaceDetectorYN.create(
            os.path.join(models_dir, YUNET_FILE), "", (320, 320), score, 0.3, 50
        )
        self.recognizer = cv2.FaceRecognizerSF.create(os.path.join(models_dir, SFACE_FILE), "")

    def detect(self, frame: np.ndarray) -> list[np.ndarray]:
        """Return raw YuNet rows (15 values) scaled to full-resolution coordinates."""
        h, w = frame.shape[:2]
        scale = min(1.0, self.detect_width / w)
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1.0 else frame
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, rows = self.detector.detect(small)
        if rows is None:
            return []
        out = []
        for row in rows:
            row = row.copy()
            row[:14] /= scale
            if min(row[2], row[3]) >= self.min_face_px:
                out.append(row)
        return out

    def embed(self, frame: np.ndarray, row: np.ndarray) -> np.ndarray:
        aligned = self.recognizer.alignCrop(frame, row)
        feat = self.recognizer.feature(aligned).flatten().astype(np.float32)
        return feat / (np.linalg.norm(feat) + 1e-9)

    def analyze(self, frame: np.ndarray) -> list[Face]:
        faces = []
        for row in self.detect(frame):
            box = tuple(int(v) for v in row[:4])
            faces.append(Face(box=box, score=float(row[14]), embedding=self.embed(frame, row)))
        return faces


def crop_snapshot(frame: np.ndarray, box: tuple[int, int, int, int], pad: float = 0.6, max_side: int = 320) -> bytes:
    """JPEG crop around a face with some context, for the attendance log."""
    x, y, w, h = box
    H, W = frame.shape[:2]
    px, py = int(w * pad), int(h * pad)
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(W, x + w + px), min(H, y + h + py)
    crop = frame[y0:y1, x0:x1]
    s = max_side / max(crop.shape[:2])
    if s < 1:
        crop = cv2.resize(crop, (int(crop.shape[1] * s), int(crop.shape[0] * s)))
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else b""
