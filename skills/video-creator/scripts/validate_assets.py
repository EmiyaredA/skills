#!/usr/bin/env python3
"""Validate pre-production assets before video generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_GATES = [
    "brief_approved",
    "characters_approved",
    "scenes_approved",
    "storyboard_approved",
    "voice_approved",
]

CHARACTER_VIEWS = ("front", "side", "back")


def load_state(project_dir: Path) -> dict:
    state_path = project_dir / "state.json"
    if not state_path.exists():
        raise FileNotFoundError(f"Missing state.json in {project_dir}")
    with state_path.open(encoding="utf-8") as f:
        return json.load(f)


def resolve_path(project_dir: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    return (project_dir / relative).resolve()


def validate_state(project_dir: Path, state: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    project_dir = project_dir.resolve()

    gates = state.get("gates", {})
    for gate in REQUIRED_GATES:
        if not gates.get(gate):
            errors.append(f"Gate not approved: {gate}")

    brief = state.get("brief", {})
    if not brief.get("title"):
        errors.append("Brief missing title")
    if not brief.get("aspect_ratio"):
        errors.append("Brief missing aspect_ratio")

    characters = state.get("characters", [])
    if not characters:
        errors.append("No characters defined")
    for char in characters:
        cid = char.get("id", "<unknown>")
        if char.get("status") != "approved":
            errors.append(f"Character {cid} not approved")
        views = char.get("views", {})
        for view in CHARACTER_VIEWS:
            rel = views.get(view)
            path = resolve_path(project_dir, rel)
            if not path or not path.exists():
                errors.append(f"Character {cid} missing {view} view: {rel}")

    scenes = state.get("scenes", [])
    if not scenes:
        errors.append("No scenes defined")
    for scene in scenes:
        sid = scene.get("id", "<unknown>")
        if scene.get("status") != "approved":
            errors.append(f"Scene {sid} not approved")
        image_rel = scene.get("image")
        image_path = resolve_path(project_dir, image_rel)
        if not image_path or not image_path.exists():
            errors.append(f"Scene {sid} missing image: {image_rel}")

    beats = state.get("storyboard", {}).get("beats", [])
    if not beats:
        errors.append("No storyboard beats defined")
    dialogue_char_ids: set[str] = set()
    for beat in beats:
        bid = beat.get("id", "<unknown>")
        if beat.get("status") != "approved":
            errors.append(f"Beat {bid} not approved")
        if not beat.get("action"):
            errors.append(f"Beat {bid} missing action")
        if not beat.get("scene_id"):
            errors.append(f"Beat {bid} missing scene_id")
        image_rel = beat.get("image")
        image_path = resolve_path(project_dir, image_rel)
        if not image_path or not image_path.exists():
            errors.append(f"Beat {bid} missing preview image: {image_rel}")
        if beat.get("dialogue"):
            dialogue_char_ids.update(beat.get("characters", []))

    char_by_id = {c.get("id"): c for c in characters}
    for cid in dialogue_char_ids:
        char = char_by_id.get(cid)
        if not char:
            errors.append(f"Beat references unknown character: {cid}")
            continue
        voice = char.get("voice", {})
        if not voice.get("description") and not voice.get("path"):
            errors.append(f"Character {cid} has dialogue but no voice configured")

    return len(errors) == 0, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate video project assets")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path("./video-project"),
        help="Project directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    project_dir = args.project.resolve()
    state = load_state(project_dir)
    ok, errors = validate_state(project_dir, state)

    if args.json:
        print(json.dumps({"ok": ok, "errors": errors}, indent=2))
    else:
        if ok:
            print("OK: All pre-production assets validated.")
        else:
            print("VALIDATION FAILED:")
            for err in errors:
                print(f"  - {err}")

    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
