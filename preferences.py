"""Validated, atomic local preferences. No registry changes or online services."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
import os
from pathlib import Path
import tempfile
import uuid
from geometry import DEFAULT_CORNERS, Point, clamp, validate_corners

CHARACTER_LABELS = {
    "gpt": "GPT",
    "claude": "Claude",
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
    "glm": "GLM",
    "grok": "Grok",
    "kimi": "Kimi",
    "qwen": "Qwen",
    "hunyuan": "Hunyuan",
    "minimax": "MiniMax",
    "stepfun": "Step",
}
REMOVED_SKINS = ("mistral", "wenxin", "mimo")


def configuration_directory(explicit: str | None, portable_root: Path) -> Path:
    """Use local app data when writable, otherwise keep settings with the app."""
    candidates = ([Path(explicit)] if explicit else [
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WindowDragon",
        portable_root / "data",
    ])
    last_error = None
    for directory in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=directory):
                pass
            return directory.resolve()
        except OSError as error:
            last_error = error
    raise OSError("No writable folder is available for app settings.") from last_error


@dataclass
class Preferences:
    height: int = 60
    edge: str = "upper"
    position: float = 0.91
    screen_name: str = ""
    skin: str = "gpt"
    visible: bool = True
    offset: int = 0
    render_revision: int = 2
    locked: bool = False
    snapping: bool = True
    free_x: float = 0.78
    free_y: float = 0.36
    corners: list[list[float]] = field(
        default_factory=lambda: [[p.x, p.y] for p in DEFAULT_CORNERS]
    )

    def points(self) -> tuple[Point, ...]:
        return tuple(Point(*p) for p in self.corners)


def preferences_from_values(values) -> Preferences:
    result = Preferences()
    try:
        if not isinstance(values, dict):
            return result
        def number(key: str, low: float, high: float, integer=False):
            value = values.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                setattr(result, key, int(clamp(value, low, high)) if integer else clamp(value, low, high))
        number("height", 32, 320, True)
        number("position", 0, 1)
        number("offset", -100, 100, True)
        number("free_x", 0, 1)
        number("free_y", 0, 1)
        if values.get("edge") in ("upper", "middle", "lower", "free"):
            result.edge = values["edge"]
        if values.get("skin") in CHARACTER_LABELS:
            result.skin = values["skin"]
        if isinstance(values.get("screen_name"), str):
            result.screen_name = values["screen_name"]
        for key in ("locked", "snapping", "visible"):
            if isinstance(values.get(key), bool):
                setattr(result, key, values[key])
        if values.get("render_revision") != 2:
            result.offset = 0
        candidate = values.get("corners")
        if isinstance(candidate, list):
            try:
                points = tuple(Point(float(p[0]), float(p[1])) for p in candidate if len(p) == 2)
                if len(candidate) == 4 and validate_corners(points):
                    result.corners = [[p.x, p.y] for p in points]
            except (TypeError, ValueError, IndexError):
                pass
    except (OSError, ValueError, TypeError):
        pass
    return result


@dataclass
class MascotRecord:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    preferences: Preferences = field(default_factory=Preferences)


@dataclass
class SessionPreferences:
    mascots: list[MascotRecord] = field(default_factory=lambda: [MascotRecord()])
    selected_id: str = ""

    def selected(self):
        return next((item for item in self.mascots if item.id == self.selected_id), self.mascots[0])


def load_session(path: Path) -> SessionPreferences:
    session = SessionPreferences()
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            return session
        if isinstance(values.get("mascots"), list):
            records, used = [], set()
            for value in values["mascots"][:64]:
                if not isinstance(value, dict) or not isinstance(value.get("preferences"), dict):
                    continue
                preferences = value["preferences"]
                if preferences.get("skin") in REMOVED_SKINS:
                    continue
                key = value.get("id")
                if not isinstance(key, str) or not key or key in used or len(key) > 128:
                    key = uuid.uuid4().hex
                used.add(key)
                records.append(MascotRecord(key, preferences_from_values(preferences)))
            if records:
                session.mascots = records
            selected = values.get("selected_id")
            session.selected_id = selected if isinstance(selected, str) and selected in used else session.mascots[0].id
        else:
            # Existing single-mascot settings migrate to the retained hand-drawn GPT.
            session.mascots[0].preferences = preferences_from_values(values)
            session.selected_id = session.mascots[0].id
    except (OSError, ValueError, TypeError):
        pass
    return session


def load_preferences(path: Path) -> Preferences:
    """Compatibility helper: return the selected mascot's preferences."""
    return load_session(path).selected().preferences


def save_preferences(path: Path, preferences: Preferences) -> None:
    atomic_json(path, asdict(preferences))


def save_session(path: Path, session: SessionPreferences) -> None:
    atomic_json(path, {"schema_version": 3, "selected_id": session.selected_id,
                       "mascots": [asdict(record) for record in session.mascots]})


def atomic_json(path: Path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, indent=2), encoding="utf-8")
    os.replace(temporary, path)
