#!/usr/bin/env python3
"""Shared helpers for reading and updating project state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def load_state(project_dir: Path) -> dict:
    state_path = project_dir / "state.json"
    if not state_path.exists():
        raise FileNotFoundError(f"Missing state.json in {project_dir}")
    with state_path.open(encoding="utf-8") as f:
        return json.load(f)


def save_state(project_dir: Path, state: dict) -> None:
    state_path = project_dir / "state.json"
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def aspect_to_size(aspect_ratio: str, base: int = 1024) -> tuple[int, int]:
    mapping = {
        "16:9": (base, int(base * 9 / 16)),
        "9:16": (int(base * 9 / 16), base),
        "1:1": (base, base),
        "4:3": (base, int(base * 3 / 4)),
        "3:4": (int(base * 3 / 4), base),
    }
    return mapping.get(aspect_ratio, (base, int(base * 9 / 16)))
