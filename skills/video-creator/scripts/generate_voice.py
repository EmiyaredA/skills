#!/usr/bin/env python3
"""Generate voice audio for a character (optional TTS provider)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_client import call_provider, load_config, save_media_from_result
from project_utils import load_state, save_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate character voice audio")
    parser.add_argument("--project", type=Path, default=Path("./video-project"))
    parser.add_argument("--character", required=True, help="Character ID, e.g. char_01")
    parser.add_argument("--text", required=True, help="Sample line for voice generation")
    parser.add_argument("--voice-id", default="default", help="Provider voice identifier")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    project_dir = args.project.resolve()
    state = load_state(project_dir)
    config = load_config(args.config)

    if "voice" not in config:
        print(
            "No voice provider configured. Set voice description in state.json instead."
        )
        raise SystemExit(1)

    char = next(
        (c for c in state.get("characters", []) if c.get("id") == args.character),
        None,
    )
    if not char:
        raise KeyError(f"Character not found: {args.character}")

    variables = {"text": args.text, "voice_id": args.voice_id}
    result = call_provider("voice", variables, config=config, config_path=args.config)

    rel_path = f"assets/{args.character}_voice.wav"
    output_path = project_dir / rel_path
    save_media_from_result(
        result, output_path, "voice", f"{args.character}_voice", config
    )

    char.setdefault("voice", {})
    char["voice"]["path"] = rel_path
    char["voice"]["source"] = "generated"
    save_state(project_dir, state)

    payload = {"character": args.character, "voice_path": rel_path}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload))


if __name__ == "__main__":
    main()
