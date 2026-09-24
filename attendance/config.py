"""Configuration loaded from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


@dataclass
class CameraConfig:
    id: str
    rtsp: str
    room: str
    ptz: bool = False
    onvif_host: str | None = None
    onvif_port: int = 80
    onvif_user: str | None = None
    onvif_pass: str | None = None
    home_preset: str | None = None


@dataclass
class Config:
    cameras: list[CameraConfig] = field(default_factory=list)

    # Models / recognition
    models_dir: str = "/app/models"
    gallery_path: str = "/app/data/gallery.npz"
    faces_dir: str = "/app/faces"
    detect_width: int = 1280
    detect_score: float = 0.8
    min_face_px: int = 40
    match_threshold: float = 0.40
    confirm_hits: int = 3
    confirm_window_sec: float = 4.0
    process_fps: float = 3.0
    motion_gate: bool = True
    motion_threshold: float = 0.004

    # Events
    cooldown_min: float = 10.0
    unknown_events: bool = True
    unknown_cooldown_min: float = 5.0
    snapshot: bool = True

    # PTZ tracking
    ptz_deadzone: float = 0.12
    ptz_speed: float = 0.5
    ptz_zoom_target_px: int = 120
    ptz_idle_return_sec: float = 20.0

    # Nextcloud
    nc_url: str = ""
    nc_user: str = ""
    nc_app_password: str = ""
    nc_verify_tls: bool = True
    spool_dir: str = "/app/data/spool"

    log_level: str = "INFO"


def load() -> Config:
    cam_ids = [c.strip() for c in (_env("CAMERAS", "") or "").split(",") if c.strip()]
    cameras: list[CameraConfig] = []
    for cid in cam_ids:
        p = f"CAM_{cid.upper()}_"
        rtsp = _env(p + "RTSP")
        if not rtsp:
            raise SystemExit(f"{p}RTSP is required for camera '{cid}'")
        cameras.append(
            CameraConfig(
                id=cid,
                rtsp=rtsp,
                room=_env(p + "ROOM", cid) or cid,
                ptz=_bool(p + "PTZ"),
                onvif_host=_env(p + "ONVIF_HOST"),
                onvif_port=_int(p + "ONVIF_PORT", 80),
                onvif_user=_env(p + "ONVIF_USER"),
                onvif_pass=_env(p + "ONVIF_PASS"),
                home_preset=_env(p + "HOME_PRESET"),
            )
        )

    return Config(
        cameras=cameras,
        models_dir=_env("MODELS_DIR", "/app/models"),
        gallery_path=_env("GALLERY_PATH", "/app/data/gallery.npz"),
        faces_dir=_env("FACES_DIR", "/app/faces"),
        detect_width=_int("DETECT_WIDTH", 1280),
        detect_score=_float("DETECT_SCORE", 0.8),
        min_face_px=_int("MIN_FACE_PX", 40),
        match_threshold=_float("MATCH_THRESHOLD", 0.40),
        confirm_hits=_int("CONFIRM_HITS", 3),
        confirm_window_sec=_float("CONFIRM_WINDOW_SEC", 4.0),
        process_fps=_float("PROCESS_FPS", 3.0),
        motion_gate=_bool("MOTION_GATE", True),
        motion_threshold=_float("MOTION_THRESHOLD", 0.004),
        cooldown_min=_float("COOLDOWN_MIN", 10.0),
        unknown_events=_bool("UNKNOWN_EVENTS", True),
        unknown_cooldown_min=_float("UNKNOWN_COOLDOWN_MIN", 5.0),
        snapshot=_bool("SNAPSHOT", True),
        ptz_deadzone=_float("PTZ_DEADZONE", 0.12),
        ptz_speed=_float("PTZ_SPEED", 0.5),
        ptz_zoom_target_px=_int("PTZ_ZOOM_TARGET_PX", 120),
        ptz_idle_return_sec=_float("PTZ_IDLE_RETURN_SEC", 20.0),
        nc_url=(_env("NC_URL", "") or "").rstrip("/"),
        nc_user=_env("NC_USER", "") or "",
        nc_app_password=_env("NC_APP_PASSWORD", "") or "",
        nc_verify_tls=_bool("NC_VERIFY_TLS", True),
        spool_dir=_env("SPOOL_DIR", "/app/data/spool"),
        log_level=_env("LOG_LEVEL", "INFO"),
    )
