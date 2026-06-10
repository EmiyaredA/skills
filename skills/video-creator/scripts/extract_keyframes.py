#!/usr/bin/env python3
"""Extract keyframes from a generated video for visual QA."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def extract_with_ffmpeg(video_path: Path, output_dir: Path, count: int) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "frame_%03d.jpg"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"select='not(mod(n\\,{max(1, 30 // count)}))',scale=1280:-1",
        "-frames:v",
        str(count),
        "-q:v",
        "2",
        str(pattern),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(str(p) for p in output_dir.glob("frame_*.jpg"))


def extract_with_pillow(video_path: Path, output_dir: Path, count: int) -> list[str]:
    """Fallback when ffmpeg is unavailable — writes placeholder QA frames."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    try:
        from PIL import Image, ImageDraw

        for i in range(count):
            out = output_dir / f"frame_{i + 1:03d}.jpg"
            img = Image.new("RGB", (1280, 720), color=(30, 30, 40))
            draw = ImageDraw.Draw(img)
            draw.text(
                (40, 40),
                f"QA Frame {i + 1}\nSource: {video_path.name}\n(ffmpeg unavailable)",
                fill=(230, 230, 230),
            )
            img.save(out, quality=90)
            paths.append(str(out))
    except ImportError:
        for i in range(count):
            out = output_dir / f"frame_{i + 1:03d}.png"
            out.write_bytes(b"\x89PNG\r\n\x1a\n" + f"qa-frame-{i + 1}".encode())
            paths.append(str(out))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract keyframes from video")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: alongside video in qa/)",
    )
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    video_path = args.video.resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    output_dir = args.output_dir or (video_path.parent / "qa" / video_path.stem)
    output_dir = output_dir.resolve()

    if shutil.which("ffmpeg"):
        try:
            frames = extract_with_ffmpeg(video_path, output_dir, args.count)
        except subprocess.CalledProcessError:
            frames = extract_with_pillow(video_path, output_dir, args.count)
    else:
        frames = extract_with_pillow(video_path, output_dir, args.count)

    payload = {"video": str(video_path), "frames": frames, "count": len(frames)}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload))


if __name__ == "__main__":
    main()
