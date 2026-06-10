#!/usr/bin/env python3
"""Generate a single video episode from approved storyboard beats."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_client import call_provider, load_config, save_media_from_result
from project_utils import load_state, save_state, utc_now_iso
from validate_assets import validate_state


def build_video_prompt(state: dict, beat_ids: list[str]) -> str:
    brief = state.get("brief", {})
    beats = state.get("storyboard", {}).get("beats", [])
    beat_map = {b.get("id"): b for b in beats}
    lines = [
        f"Title: {brief.get('title', '')}",
        f"Style: {brief.get('style', '')}",
        f"Mood: {brief.get('mood', '')}",
        "Story beats:",
    ]
    for bid in beat_ids:
        beat = beat_map.get(bid)
        if not beat:
            raise KeyError(f"Beat not found: {bid}")
        dialogue = beat.get("dialogue", "")
        dialogue_part = f' Dialogue: "{dialogue}"' if dialogue else ""
        lines.append(
            f"- {bid}: scene={beat.get('scene_id')} "
            f"characters={','.join(beat.get('characters', []))} "
            f"action={beat.get('action')}{dialogue_part}"
        )
    return "\n".join(lines)


def collect_reference_images(project_dir: Path, state: dict, beat_ids: list[str]) -> list[str]:
    refs: list[str] = []
    beats = {b.get("id"): b for b in state.get("storyboard", {}).get("beats", [])}
    for bid in beat_ids:
        beat = beats.get(bid, {})
        image_rel = beat.get("image")
        if image_rel:
            refs.append(str((project_dir / image_rel).resolve()))
    return refs


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate one video episode")
    parser.add_argument("--project", type=Path, default=Path("./video-project"))
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--beats", required=True, help="Comma-separated beat IDs")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    project_dir = args.project.resolve()
    state = load_state(project_dir)
    beat_ids = [b.strip() for b in args.beats.split(",") if b.strip()]

    if not args.skip_validate:
        ok, errors = validate_state(project_dir, state)
        if not ok:
            print("VALIDATION FAILED — cannot generate video:")
            for err in errors:
                print(f"  - {err}")
            raise SystemExit(1)

    config = load_config(args.config)
    brief = state.get("brief", {})
    prompt = build_video_prompt(state, beat_ids)
    reference_images = collect_reference_images(project_dir, state, beat_ids)

    variables = {
        "prompt": prompt,
        "duration": str(brief.get("duration_target_sec", 10)),
        "aspect_ratio": brief.get("aspect_ratio", "16:9"),
        "reference_images": json.dumps(reference_images),
    }

    state["current_stage"] = "generating"
    save_state(project_dir, state)

    result = call_provider("video", variables, config=config, config_path=args.config)
    video_rel = f"output/ep{args.episode:02d}.mp4"
    output_path = project_dir / video_rel
    save_media_from_result(
        result, output_path, "video", f"episode_{args.episode}", config
    )

    episode_entry = {
        "episode": args.episode,
        "video_path": video_rel,
        "beats_used": beat_ids,
        "generated_at": utc_now_iso(),
    }
    episodes = state.setdefault("episodes", [])
    episodes = [e for e in episodes if e.get("episode") != args.episode]
    episodes.append(episode_entry)
    state["episodes"] = sorted(episodes, key=lambda e: e.get("episode", 0))
    state["current_stage"] = "review"

    save_state(project_dir, state)

    payload = {"episode": args.episode, "video_path": video_rel, "beats_used": beat_ids}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload))


if __name__ == "__main__":
    main()
