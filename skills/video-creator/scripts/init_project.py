#!/usr/bin/env python3
"""Initialize a video project directory with state.json and folders."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def default_state(title: str = "") -> dict:
    return {
        "project_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "brief": {
            "title": title,
            "type": "",
            "style": "",
            "aspect_ratio": "16:9",
            "duration_target_sec": 10,
            "mood": "",
            "audience": "",
            "story_summary": "",
        },
        "characters": [],
        "scenes": [],
        "storyboard": {"beats": []},
        "episodes": [],
        "current_stage": "brief",
        "gates": {
            "brief_approved": False,
            "characters_approved": False,
            "scenes_approved": False,
            "storyboard_approved": False,
            "voice_approved": False,
        },
    }


def init_project(project_dir: Path, title: str = "", force: bool = False) -> Path:
    project_dir = project_dir.resolve()
    state_path = project_dir / "state.json"

    if state_path.exists() and not force:
        raise FileExistsError(
            f"Project already exists at {project_dir}. Use --force to reinitialize."
        )

    for subdir in ("assets", "output", "docs"):
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    state = default_state(title=title)
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    brief_template = project_dir / "docs" / "brief.md"
    if not brief_template.exists():
        brief_template.write_text(
            "# Video Brief\n\nFill in project requirements during Stage 1.\n",
            encoding="utf-8",
        )

    return state_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize a video-creator project")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path("./video-project"),
        help="Project directory (default: ./video-project)",
    )
    parser.add_argument("--title", default="", help="Optional project title")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing state.json",
    )
    args = parser.parse_args()

    state_path = init_project(args.project, title=args.title, force=args.force)
    print(f"Initialized project at {args.project.resolve()}")
    print(f"State file: {state_path}")


if __name__ == "__main__":
    main()
