#!/usr/bin/env python3
"""End-to-end mock workflow verification for video-creator skill."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
MOCK_CONFIG = SKILL_ROOT / "config" / "providers.mock.json"
PROJECT = SKILL_ROOT / "test-video-project"


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


def main() -> None:
    if PROJECT.exists():
        import shutil

        shutil.rmtree(PROJECT)

    run([sys.executable, str(SCRIPTS / "init_project.py"), "--project", str(PROJECT), "--title", "Mock Test"])

    state_path = PROJECT / "state.json"
    with state_path.open(encoding="utf-8") as f:
        state = json.load(f)

    state["brief"].update(
        {
            "type": "short story",
            "style": "cinematic",
            "mood": "adventurous",
            "story_summary": "Explorer finds artifact",
        }
    )
    state["characters"] = [
        {
            "id": "char_01",
            "name": "Explorer",
            "description": "Young adventurer",
            "views": {},
            "reference_upload": None,
            "voice": {
                "source": "ai_recommended",
                "path": "",
                "description": "Female, warm tone",
            },
            "status": "draft",
        }
    ]
    state["scenes"] = [
        {
            "id": "scene_01",
            "name": "Forest",
            "description": "Misty forest clearing",
            "image": "",
            "status": "draft",
        }
    ]
    state["storyboard"]["beats"] = [
        {
            "id": "beat_01",
            "scene_id": "scene_01",
            "characters": ["char_01"],
            "action": "Reaches for glowing artifact",
            "dialogue": "What is this?",
            "camera": "medium shot",
            "image": "",
            "status": "draft",
        }
    ]
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    cfg = ["--config", str(MOCK_CONFIG)]

    run(
        [
            sys.executable,
            str(SCRIPTS / "generate_image.py"),
            "--project",
            str(PROJECT),
            "--type",
            "character_three_view",
            "--id",
            "char_01",
            "--prompt",
            "Young explorer, cinematic style",
            *cfg,
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "generate_image.py"),
            "--project",
            str(PROJECT),
            "--type",
            "scene",
            "--id",
            "scene_01",
            "--prompt",
            "Misty forest clearing at dawn",
            *cfg,
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "generate_image.py"),
            "--project",
            str(PROJECT),
            "--type",
            "storyboard",
            "--id",
            "beat_01",
            "--prompt",
            "Explorer reaching for artifact in forest",
            *cfg,
        ]
    )

    with state_path.open(encoding="utf-8") as f:
        state = json.load(f)

    for char in state["characters"]:
        char["status"] = "approved"
    for scene in state["scenes"]:
        scene["status"] = "approved"
    for beat in state["storyboard"]["beats"]:
        beat["status"] = "approved"
    state["gates"] = {k: True for k in state["gates"]}
    state["current_stage"] = "preflight"
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    run([sys.executable, str(SCRIPTS / "validate_assets.py"), "--project", str(PROJECT)])

    run(
        [
            sys.executable,
            str(SCRIPTS / "generate_video.py"),
            "--project",
            str(PROJECT),
            "--episode",
            "1",
            "--beats",
            "beat_01",
            *cfg,
        ]
    )

    video = PROJECT / "output" / "ep01.mp4"
    if not video.exists():
        raise RuntimeError("Video output missing")

    run(
        [
            sys.executable,
            str(SCRIPTS / "extract_keyframes.py"),
            "--video",
            str(video),
            "--count",
            "3",
        ]
    )

    with state_path.open(encoding="utf-8") as f:
        final = json.load(f)

    assert final["episodes"], "No episodes recorded"
    assert final["current_stage"] == "review"
    print("OK: Mock workflow verified successfully.")
    print(f"  Project: {PROJECT}")
    print(f"  Video:   {video}")
    print(f"  Episodes: {len(final['episodes'])}")


if __name__ == "__main__":
    main()
