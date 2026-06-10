#!/usr/bin/env python3
"""Provider-agnostic HTTP client for image, video, and voice APIs."""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import time
import zlib
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATHS = [
    SKILL_ROOT / "config" / "providers.yaml",
    SKILL_ROOT / "config" / "providers.yaml.example",
]


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or next(
        (p for p in DEFAULT_CONFIG_PATHS if p.exists()), DEFAULT_CONFIG_PATHS[0]
    )
    if not path.exists():
        raise FileNotFoundError(
            f"Provider config not found. Copy config/providers.yaml.example to "
            f"config/providers.yaml and configure your APIs."
        )
    with path.open(encoding="utf-8") as f:
        if path.suffix == ".json":
            return json.load(f) or {}
        import yaml

        return yaml.safe_load(f) or {}


def is_mock_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("mock", {}).get("enabled", False))


def get_nested(data: Any, path: str | None) -> Any:
    if not path:
        return data
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def render_template(obj: Any, variables: dict[str, str]) -> Any:
    if isinstance(obj, str):
        result = obj
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", value)
        if "{{" in result and "}}" in result:
            leftover = re.findall(r"\{\{([^}]+)\}\}", result)
            if leftover:
                raise ValueError(f"Unresolved template placeholders: {leftover}")
        return result
    if isinstance(obj, list):
        return [render_template(item, variables) for item in obj]
    if isinstance(obj, dict):
        return {k: render_template(v, variables) for k, v in obj.items()}
    return obj


def build_auth_headers(provider: dict[str, Any]) -> dict[str, str]:
    env_var = provider.get("auth_env_var")
    if not env_var:
        return {}
    token = os.environ.get(env_var)
    if not token:
        raise EnvironmentError(
            f"Missing API key: set environment variable {env_var}"
        )
    header = provider.get("auth_header", "Authorization")
    prefix = provider.get("auth_prefix", "")
    return {header: f"{prefix}{token}"}


def download_binary(url: str, headers: dict[str, str] | None = None) -> bytes:
    import httpx

    with httpx.Client(timeout=120.0) as client:
        response = client.get(url, headers=headers or {})
        response.raise_for_status()
        return response.content


def _write_minimal_png(output_path: Path, size: tuple[int, int], rgb: tuple[int, int, int]) -> None:
    width, height = size

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b""
    row = b"\x00" + bytes(rgb) * width
    for _ in range(height):
        raw += row
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    output_path.write_bytes(png)


def save_placeholder_image(output_path: Path, label: str, size: tuple[int, int] = (512, 512)) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", size, color=(40, 44, 52))
        draw = ImageDraw.Draw(img)
        draw.multiline_text((20, 20), f"MOCK\n{label}", fill=(220, 220, 220))
        img.save(output_path)
    except ImportError:
        _write_minimal_png(output_path, size, (40, 44, 52))
    return output_path


def save_placeholder_video(output_path: Path, label: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal valid MP4 header stub for testing; ffmpeg not required for validate flow
    output_path.write_bytes(
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
        + f"MOCK VIDEO: {label}".encode("utf-8")
    )
    return output_path


def save_placeholder_audio(output_path: Path, label: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"RIFF" + b"\x00\x00\x00\x00WAVE" + label.encode("utf-8"))
    return output_path


def call_provider(
    slot: str,
    variables: dict[str, str],
    config: dict[str, Any] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    cfg = config or load_config(config_path)
    if is_mock_enabled(cfg):
        return {"mock": True, "slot": slot, "variables": variables}

    import httpx

    provider = cfg.get(slot)
    if not provider:
        raise KeyError(f"No provider configured for slot '{slot}'")

    method = provider.get("method", "POST").upper()
    url = provider["base_url"].rstrip("/") + provider["endpoint"]
    headers = {"Content-Type": "application/json", **build_auth_headers(provider)}
    body = render_template(provider.get("request_template", {}), variables)

    with httpx.Client(timeout=300.0) as client:
        if method == "POST":
            response = client.post(url, headers=headers, json=body)
        elif method == "GET":
            response = client.get(url, headers=headers, params=body)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        response.raise_for_status()

        response_format = provider.get("response_format", "url")
        if response_format == "binary":
            return {"binary": response.content}

        data = response.json()
        poll_cfg = provider.get("poll", {})
        if poll_cfg.get("enabled"):
            task_id = str(get_nested(data, poll_cfg.get("task_id_path", "id")))
            data = poll_until_ready(client, provider, task_id, headers)

        if response_format == "base64":
            encoded = get_nested(data, provider.get("response_image_path", "data.0.b64_json"))
            if not encoded:
                raise ValueError(f"No base64 payload in response for slot '{slot}'")
            return {"base64": encoded}

        media_path = provider.get("response_image_path") or provider.get("response_video_path")
        media_url = get_nested(data, media_path)
        if not media_url:
            raise ValueError(f"No media URL in response at path '{media_path}'")
        return {"url": media_url, "raw": data}


def poll_until_ready(
    client: httpx.Client,
    provider: dict[str, Any],
    task_id: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    poll = provider["poll"]
    endpoint = poll["endpoint"].replace("{{task_id}}", task_id)
    url = provider["base_url"].rstrip("/") + endpoint
    ready_status = poll.get("ready_status", "completed")
    interval = poll.get("interval_sec", 5)
    max_attempts = poll.get("max_attempts", 60)

    for _ in range(max_attempts):
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        status = get_nested(data, poll.get("status_path", "status"))
        if status == ready_status:
            return data
        time.sleep(interval)
    raise TimeoutError(f"Polling timed out for task {task_id}")


def save_media_from_result(
    result: dict[str, Any],
    output_path: Path,
    slot: str,
    label: str,
    config: dict[str, Any] | None = None,
) -> Path:
    cfg = config or load_config()
    if result.get("mock") or is_mock_enabled(cfg):
        if slot == "image":
            return save_placeholder_image(output_path, label)
        if slot == "video":
            return save_placeholder_video(output_path, label)
        if slot == "voice":
            return save_placeholder_audio(output_path, label)
        raise ValueError(f"Unknown mock slot: {slot}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if "binary" in result:
        output_path.write_bytes(result["binary"])
        return output_path

    if "base64" in result:
        output_path.write_bytes(base64.b64decode(result["base64"]))
        return output_path

    if "url" in result:
        content = download_binary(result["url"])
        output_path.write_bytes(content)
        return output_path

    raise ValueError(f"Unsupported media result for slot '{slot}': {result.keys()}")
