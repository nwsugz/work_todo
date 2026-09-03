"""업무와 규칙을 사용자 폴더에 JSON으로 보관합니다."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .models import Task
from .rules import DEFAULT_RULES, validate


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "TodoTBD"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tasks_path() -> Path:
    return data_dir() / "tasks.json"


def rules_path() -> Path:
    return data_dir() / "rules.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def _write_atomic(path: Path, payload: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_tasks() -> list[Task]:
    path = tasks_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 파일이 깨졌으면 백업만 남기고 빈 목록으로 시작합니다.
        shutil.copy2(path, path.with_suffix(".broken.json"))
        return []
    items = raw.get("tasks", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    return [Task.from_dict(item) for item in items if isinstance(item, dict)]


def save_tasks(tasks: list[Task]) -> None:
    _write_atomic(tasks_path(), {"version": 1, "tasks": [t.to_dict() for t in tasks]})


def load_rules() -> tuple[dict[str, Any], str | None]:
    """(규칙, 경고 메시지)를 돌려줍니다. 파일이 없으면 기본 규칙을 만들어 둡니다."""
    path = rules_path()
    if not path.exists():
        _write_atomic(path, DEFAULT_RULES)
        return json.loads(json.dumps(DEFAULT_RULES)), None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return json.loads(json.dumps(DEFAULT_RULES)), f"규칙 파일을 읽지 못해 기본 규칙을 씁니다: {exc}"
    problem = validate(raw)
    if problem:
        return json.loads(json.dumps(DEFAULT_RULES)), f"{problem} 기본 규칙을 대신 적용했습니다."
    return raw, None


def save_rules(rules: dict[str, Any]) -> None:
    _write_atomic(rules_path(), rules)


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_settings(settings: dict[str, Any]) -> None:
    _write_atomic(settings_path(), settings)
