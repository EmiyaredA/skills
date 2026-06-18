"""语音：列出可用音色，或为角色台词合成语音（TTS）。

列出系统音色：
  python gen_voice.py --list

为角色合成台词（写入 assets/voices/，并登记到角色的 voice 字段）：
  python gen_voice.py --project P --character char_01 --voice-id female_0033_b \
      --text "你怎么这么晚才来？"

  （--mock 仅 selftest 自检用，勿作交付）
"""
import argparse
import json
import os

import sa_client as sa
import project_utils as pu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="列出可用音色")
    ap.add_argument("--voice-type", default="all",
                    choices=["all", "system", "voice_clone", "voice_generation"])
    ap.add_argument("--project", default=None)
    ap.add_argument("--character", default=None)
    ap.add_argument("--voice-id", default=None, help="不填则用项目配置 audio.voice_id")
    ap.add_argument("--text", default=None)
    ap.add_argument("--format", default=None, choices=["mp3", "wav", "pcm", "flac"])
    ap.add_argument("--speed", type=float, default=None)
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    if args.list:
        data = sa.list_voices(args.voice_type)
        for group in ("system_voice", "voice_cloning", "voice_generation"):
            voices = data.get(group) or []
            if voices:
                print(f"\n== {group} ==")
                for v in voices:
                    desc = "，".join(v.get("description") or [])
                    print(f"  {v.get('voice_id'):<24} {v.get('voice_name','')}  {desc}")
        return

    if not (args.project and args.character and args.text):
        ap.error("合成语音需要 --project --character --text（--voice-id 可由项目配置提供）")

    state = pu.load_state(args.project)

    pu.use_project_key(args.project)
    if args.mock:
        print("⚠ MOCK：仅供 selftest 自检，写占位文件，切勿作为成品交付。")
    else:
        pu.require_key(args.project)
    acfg = state["config"].get("audio", {})
    voice_id = args.voice_id or acfg.get("voice_id")
    fmt = args.format or acfg.get("format", "mp3")
    speed = args.speed if args.speed is not None else acfg.get("speed", 1.0)
    model = acfg.get("tts_model", sa.DEFAULT_TTS_MODEL)
    if not voice_id:
        ap.error("未指定音色：请用 --voice-id，或在应用「设置」里设置默认音色 audio.voice_id（先 gen_voice.py --list 选）")

    char = pu.find(state["characters"], args.character)
    if not char:
        ap.error(f"找不到角色 {args.character}，请先生成角色。")

    dest = os.path.join(args.project, "assets/voices", f"{args.character}.{fmt}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if args.mock:
        with open(dest, "wb") as f:
            f.write(b"MOCK_AUDIO")
    else:
        audio = sa.tts(args.text, voice_id, model=model, fmt=fmt, speed=speed)
        with open(dest, "wb") as f:
            f.write(audio)

    voice_rec = {"source": "tts", "voice_id": voice_id,
                 "sample_text": args.text, "sample": os.path.relpath(dest, args.project)}

    def _apply(st):
        c = pu.find(st.setdefault("characters", []), args.character)
        if c:
            c["voice"] = voice_rec
        pu.log(st, f"为 {args.character} 合成语音（voice_id={voice_id}）")
    pu.update_state(args.project, _apply)   # 并发安全：重载最新 state 再写
    print(f"  ✓ {dest}")
    print(f"已登记角色 {args.character} 的音色 {voice_id}")


if __name__ == "__main__":
    main()
