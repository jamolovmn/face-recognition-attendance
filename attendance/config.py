"""Configuration loaded from environment variables (see .env.example)."""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field


def load_dotenv(path: str = ".env") -> None:
    """Read KEY=VALUE lines into the environment (Docker does this itself; needed on Windows)."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


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


def _hhmm(value: str) -> int:
    h, m = value.strip().split(":")
    return int(h) * 60 + int(m)


def _hours(value: str | None) -> tuple[int, int] | None:
    """'07:00-20:00' -> (420, 1200). Ranges over midnight ('22:00-06:00') are allowed."""
    if not value:
        return None
    start, end = value.split("-")
    return _hhmm(start), _hhmm(end)


def _days(value: str | None) -> frozenset[int]:
    """'1-5' or '1,2,3,4,5,6' -> ISO weekdays."""
    days: set[int] = set()
    for part in (value or "1-7").split(","):
        if "-" in part:
            a, b = part.split("-")
            days.update(range(int(a), int(b) + 1))
        elif part.strip():
            days.add(int(part))
    return frozenset(d for d in days if 1 <= d <= 7)


@dataclass
class CameraConfig:
    id: str
    rtsp: str
    room: str
    rtsp_sub: str | None = None  # low-res stream for cheap motion watching
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
    models_dir: str = "models"
    gallery_path: str = "data/gallery.npz"
    faces_dir: str = "faces"
    detect_width: int = 1280
    detect_score: float = 0.8
    min_face_px: int = 40
    match_threshold: float = 0.40
    confirm_hits: int = 3
    confirm_window_sec: float = 4.0
    process_fps: float = 3.0
    calm_fps: float = 1.0
    calm_detect_width: int = 640
    reverify_sec: float = 5.0
    motion_gate: bool = True
    motion_threshold: float = 0.004
    active_hold_sec: float = 6.0

    # Schedule
    active_hours: tuple[int, int] | None = None  # minutes since midnight (start, end); None = always
    active_days: frozenset[int] = frozenset(range(1, 8))  # ISO weekdays, 1 = Monday
    off_hours_mode: str = "off"  # off = disconnect cameras, watch = keep working

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

    # Automatic photo collection of unknown people + people folder in Nextcloud
    collect_faces: bool = False
    collect_per_person: int = 20
    collect_min_face_px: int = 80
    collect_min_sharpness: float = 50.0
    new_faces_dir: str = "data/new_faces"
    nc_people_dir: str | None = None  # e.g. "Attendance/People"; mirrored into faces_dir
    nc_new_faces_dir: str = "Attendance/New faces"
    sync_sec: float = 60.0

    # Nextcloud
    nc_url: str = ""
    nc_user: str = ""
    nc_app_password: str = ""
    nc_verify_tls: bool = True
    spool_dir: str = "data/spool"

    # Failover between several camera nodes (only one runs the cameras)
    failover: bool = False
    node_id: str = ""
    node_priority: int = 1  # lower = preferred
    lease_ttl_sec: float = 45.0

    log_level: str = "INFO"
    log_file: str | None = None


def load() -> Config:
    load_dotenv()
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
                rtsp_sub=_env(p + "RTSP_SUB"),
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
        models_dir=_env("MODELS_DIR", "models"),
        gallery_path=_env("GALLERY_PATH", "data/gallery.npz"),
        faces_dir=_env("FACES_DIR", "faces"),
        detect_width=_int("DETECT_WIDTH", 1280),
        detect_score=_float("DETECT_SCORE", 0.8),
        min_face_px=_int("MIN_FACE_PX", 40),
        match_threshold=_float("MATCH_THRESHOLD", 0.40),
        confirm_hits=_int("CONFIRM_HITS", 3),
        confirm_window_sec=_float("CONFIRM_WINDOW_SEC", 4.0),
        process_fps=_float("PROCESS_FPS", 3.0),
        calm_fps=_float("CALM_FPS", 1.0),
        calm_detect_width=_int("CALM_DETECT_WIDTH", 640),
        reverify_sec=_float("REVERIFY_SEC", 5.0),
        motion_gate=_bool("MOTION_GATE", True),
        motion_threshold=_float("MOTION_THRESHOLD", 0.004),
        active_hold_sec=_float("ACTIVE_HOLD_SEC", 6.0),
        active_hours=_hours(_env("ACTIVE_HOURS")),
        active_days=_days(_env("ACTIVE_DAYS", "1-7")),
        off_hours_mode=(_env("OFF_HOURS_MODE", "off") or "off").lower(),
        cooldown_min=_float("COOLDOWN_MIN", 10.0),
        unknown_events=_bool("UNKNOWN_EVENTS", True),
        unknown_cooldown_min=_float("UNKNOWN_COOLDOWN_MIN", 5.0),
        snapshot=_bool("SNAPSHOT", True),
        ptz_deadzone=_float("PTZ_DEADZONE", 0.12),
        ptz_speed=_float("PTZ_SPEED", 0.5),
        ptz_zoom_target_px=_int("PTZ_ZOOM_TARGET_PX", 120),
        ptz_idle_return_sec=_float("PTZ_IDLE_RETURN_SEC", 20.0),
        collect_faces=_bool("COLLECT_FACES", False),
        collect_per_person=_int("COLLECT_PER_PERSON", 20),
        collect_min_face_px=_int("COLLECT_MIN_FACE_PX", 80),
        collect_min_sharpness=_float("COLLECT_MIN_SHARPNESS", 50.0),
        new_faces_dir=_env("NEW_FACES_DIR", "data/new_faces"),
        nc_people_dir=_env("NC_PEOPLE_DIR"),
        nc_new_faces_dir=_env("NC_NEW_FACES_DIR", "Attendance/New faces"),
        sync_sec=_float("SYNC_SEC", 60.0),
        nc_url=(_env("NC_URL", "") or "").rstrip("/"),
        nc_user=_env("NC_USER", "") or "",
        nc_app_password=_env("NC_APP_PASSWORD", "") or "",
        nc_verify_tls=_bool("NC_VERIFY_TLS", True),
        spool_dir=_env("SPOOL_DIR", "data/spool"),
        failover=_bool("FAILOVER", False),
        node_id=_env("NODE_ID") or socket.gethostname(),
        node_priority=_int("NODE_PRIORITY", 1),
        lease_ttl_sec=_float("LEASE_TTL_SEC", 45.0),
        log_level=_env("LOG_LEVEL", "INFO"),
        log_file=_env("LOG_FILE"),
    )
