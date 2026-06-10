#!/usr/bin/env python3
"""Generate images for characters, scenes, or storyboard beats."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_client import call_provider, load_config, save_media_from_result
from project_utils import aspect_to_size, load_state, save_state

SKILL_ROOT = Path(__file__).resolve().parent.parent


def update_character_views(
    state: dict, char_id: str, view: str, rel_path: str
) -> None:
    for char in state.get("characters", []):
        if char.get("id") == char_id:
            char.setdefault("views", {})[view] = rel_path
            return
    raise KeyError(f"Character not found: {char_id}")


def update_scene_image(state: dict, scene_id: str, rel_path: str) -> None:
    for scene in state.get("scenes", []):
        if scene.get("id") == scene_id:
            scene["image"] = rel_path
            return
    raise KeyError(f"Scene not found: {scene_id}")


def update_beat_image(state: dict, beat_id: str, rel_path: str) -> None:
    for beat in state.get("storyboard", {}).get("beats", []):
        if beat.get("id") == beat_id:
            beat["image"] = rel_path
            return
    raise KeyError(f"Beat not found: {beat_id}")


def generate_character_three_view(
    project_dir: Path,
    state: dict,
    char_id: str,
    prompt: str,
    reference: Path | None,
    config_path: Path | None,
) -> list[str]:
    config = load_config(config_path)
    aspect = state.get("brief", {}).get("aspect_ratio", "16:9")
    width, height = aspect_to_size(aspect, base=768)
    outputs: list[str] = []

    for view in ("front", "side", "back"):
        view_prompt = (
            f"{prompt}. Character turnaround sheet, {view} view, "
            "consistent design, neutral background, full body."
        )
        rel_path = f"assets/{char_id}_{view}.png"
        output_path = project_dir / rel_path
        variables = {
            "prompt": view_prompt,
            "reference_url": str(reference) if reference else "",
            "width": str(width),
            "height": str(height),
        }
        result = call_provider("image", variables, config=config, config_path=config_path)
        save_media_from_result(result, output_path, "image", f"{char_id}_{view}", config)
        update_character_views(state, char_id, view, rel_path)
        outputs.append(rel_path)
    return outputs


def generate_scene_image(
    project_dir: Path,
    state: dict,
    scene_id: str,
    prompt: str,
    reference: Path | None,
    config_path: Path | None,
) -> str:
    config = load_config(config_path)
    aspect = state.get("brief", {}).get("aspect_ratio", "16:9")
    width, height = aspect_to_size(aspect, base=1024)
    rel_path = f"assets/{scene_id}.png"
    output_path = project_dir / rel_path
    variables = {
        "prompt": prompt,
        "reference_url": str(reference) if reference else "",
        "width": str(width),
        "height": str(height),
    }
    result = call_provider("image", variables, config=config, config_path=config_path)
    save_media_from_result(result, output_path, "image", scene_id, config)
    update_scene_image(state, scene_id, rel_path)
    return rel_path


def generate_storyboard_image(
    project_dir: Path,
    state: dict,
    beat_id: str,
    prompt: str,
    reference: Path | None,
    config_path: Path | None,
) -> str:
    config = load_config(config_path)
    aspect = state.get("brief", {}).get("aspect_ratio", "16:9")
    width, height = aspect_to_size(aspect, base=1024)
    rel_path = f"assets/{beat_id}.png"
    output_path = project_dir / rel_path
    variables = {
        "prompt": prompt,
        "reference_url": str(reference) if reference else "",
        "width": str(width),
        "height": str(height),
    }
    result = call_provider("image", variables, config=config, config_path=config_path)
    save_media_from_result(result, output_path, "image", beat_id, config)
    update_beat_image(state, beat_id, rel_path)
    return rel_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate project images via API")
    parser.add_argument("--project", type=Path, default=Path("./video-project"))
    parser.add_argument(
        "--type",
        required=True,
        choices=["character_three_view", "scene", "storyboard"],
    )
    parser.add_argument("--id", required=True, help="char_01, scene_01, or beat_01")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--reference", type=Path, default=None)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to providers.yaml (default: skill config/providers.yaml)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    project_dir = args.project.resolve()
    state = load_state(project_dir)

    if args.type == "character_three_view":
        outputs = generate_character_three_view(
            project_dir, state, args.id, args.prompt, args.reference, args.config
        )
        payload = {"type": args.type, "id": args.id, "outputs": outputs}
    elif args.type == "scene":
        output = generate_scene_image(
            project_dir, state, args.id, args.prompt, args.reference, args.config
        )
        payload = {"type": args.type, "id": args.id, "output": output}
    else:
        output = generate_storyboard_image(
            project_dir, state, args.id, args.prompt, args.reference, args.config
        )
        payload = {"type": args.type, "id": args.id, "output": output}

    save_state(project_dir, state)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload))


if __name__ == "__main__":
    main()
