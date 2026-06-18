"""生成视频片段。支持样片（最省积分）与成片，以及多种生成模式。

模式由传入的输入自动判定，并写入 state：
  纯文生视频          只给 --prompt
  首帧 / 尾帧 / 首尾帧  --first-frame / --last-frame
  参考图驱动          --reference a.png,b.png
  承接前置视频        --prev-video <已托管URL>  （或先用 extract_frames.py 取末帧作 --first-frame）
  续接后置视频        --next-video <已托管URL>  （或取后片首帧作 --last-frame）
  音频驱动            --audio voice.mp3

示例（样片，480p 最省）：
  python gen_video.py --project P --id clip_01 --sample \
      --prompt "林夏推开便利店门，回头一笑" \
      --first-frame assets/shots/shot_01.png --duration 5

示例（成片，1080p）：
  python gen_video.py --project P --id clip_01 --resolution 1080p \
      --prompt "..." --first-frame assets/shots/shot_01.png \
      --last-frame assets/shots/shot_02.png --duration 8

  --no-audio 关闭生成音轨。（--mock 仅 selftest 自检用，勿作交付）
"""
import argparse
import os

import sa_client as sa
import project_utils as pu


def derive_mode(first, last, refs, prev_v, next_v, audio):
    if prev_v:
        return "continue_prev"
    if next_v:
        return "continue_next"
    if first and last:
        return "first_last"
    if first:
        return "first_frame"
    if last:
        return "last_frame"
    if refs:
        return "reference"
    if audio:
        return "audio_driven"
    return "text_to_video"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--first-frame", default=None)
    ap.add_argument("--last-frame", default=None)
    ap.add_argument("--reference", default=None, help="参考图，逗号分隔")
    ap.add_argument("--characters", default=None, help="出场角色 id，逗号分隔；自动注入角色锚点+各角色参考图")
    ap.add_argument("--scene", default=None, help="场景 id；自动把场景图作参考")
    ap.add_argument("--prev-video", default=None, help="承接的前置视频（http(s) URL）")
    ap.add_argument("--next-video", default=None, help="续接的后置视频（http(s) URL）")
    ap.add_argument("--audio", default=None, help="驱动音频（本地路径或URL）")
    ap.add_argument("--shots", default=None, help="关联的分镜 id，逗号分隔")
    ap.add_argument("--duration", type=int, default=None, help="秒，4-15")
    ap.add_argument("--ratio", default=None)
    ap.add_argument("--model", default=None, help="覆盖项目默认视频模型")
    ap.add_argument("--resolution", default=None, choices=["480p", "720p", "1080p"])
    ap.add_argument("--sample", action="store_true", help="样片：默认 480p 最省积分")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--watermark", dest="watermark", action="store_true", default=None)
    ap.add_argument("--no-watermark", dest="watermark", action="store_false")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    state = pu.load_state(args.project)

    pu.use_project_key(args.project)
    if args.mock:
        print("⚠ MOCK：仅供 selftest 自检，写占位文件，切勿作为成品交付。")
    else:
        pu.require_key(args.project)
    cfg = state["config"]
    vcfg = cfg.get("video", {})
    ratio = args.ratio or cfg["ratio"]
    resolution = args.resolution or (vcfg.get("resolution_sample", "480p") if args.sample
                                     else vcfg.get("resolution_final", "720p"))
    duration = args.duration if args.duration is not None else vcfg.get("duration_default", 5)
    generate_audio = (not args.no_audio) and vcfg.get("generate_audio", True)
    watermark = vcfg.get("watermark", True) if args.watermark is None else args.watermark
    refs = [r.strip() for r in args.reference.split(",")] if args.reference else []

    # 出场角色：注入身份锚点到 prompt + 把每个角色的设定图作参考（视频支持多参考图）。
    # 这是防止"角色性别错/衣服对不上/角色消失或重复"的关键。
    char_ids = [c.strip() for c in args.characters.split(",") if c.strip()] if args.characters else []
    prompt = args.prompt
    if char_ids:
        anchor = pu.character_anchor(state, char_ids)
        if anchor:
            prompt = anchor + "本镜：" + args.prompt
        for cid in char_ids:
            img = pu.character_image(state, cid)
            if img and img not in refs:
                refs.append(img)

    mode = derive_mode(args.first_frame, args.last_frame, refs,
                       args.prev_video, args.next_video, args.audio)
    cost = sa.estimate_video(resolution, duration)
    kind = "sample" if args.sample else "final"
    dest = os.path.join(args.project, "output", f"{args.id}_{kind}.mp4")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    print(f"模式={mode}  画质={resolution}  时长={duration}s  音轨={generate_audio}  参考成本~{cost:.2f}元")
    if char_ids:
        print(f"  ↳ 出场角色：{','.join(char_ids)}；已注入身份锚点 + {len(refs)} 张参考图（防角色漂移/消失）")

    record = {
        "id": args.id, "kind": kind, "mode": mode, "prompt": args.prompt,
        "model": args.model or vcfg.get("model", sa.DEFAULT_VIDEO_MODEL),
        "resolution": resolution, "duration": duration, "ratio": ratio,
        "shot_ids": args.shots.split(",") if args.shots else [],
        "characters": char_ids,
        "inputs": {"first_frame": args.first_frame, "last_frame": args.last_frame,
                   "reference": refs, "prev_video": args.prev_video,
                   "next_video": args.next_video, "audio": args.audio},
        "cost_estimate": round(cost, 2), "status": "generating",
    }

    if args.mock:
        with open(dest, "wb") as f:
            f.write(b"MOCK_MP4_PLACEHOLDER")
        record.update(status="done", local_path=os.path.relpath(dest, args.project),
                      task_id="mock", video_url="")
        print(f"  ✓ (mock) {dest}")
    else:
        content = sa.build_video_content(
            prompt, first_frame=args.first_frame, last_frame=args.last_frame,
            reference_images=refs, prev_video=args.prev_video,
            next_video=args.next_video, audio=args.audio)
        task_id = sa.video_create(
            content, duration, resolution, ratio,
            model=args.model or vcfg.get("model", sa.DEFAULT_VIDEO_MODEL),
            generate_audio=generate_audio, watermark=watermark)
        record["task_id"] = task_id
        print(f"  任务已提交 task_id={task_id}，轮询中…")

        def show(status, progress):
            bar = f" {progress}%" if progress is not None else ""
            print(f"    状态：{status}{bar}")

        st = sa.video_poll(task_id, on_progress=show)
        sa.download(st["video_url"], dest)
        record.update(status="done", video_url=st["video_url"],
                      local_path=os.path.relpath(dest, args.project))
        print(f"  ✓ {dest}")

    existing = pu.find(state["clips"], args.id)
    if existing:
        existing.update(record)
    else:
        state["clips"].append(record)
    pu.log(state, f"生成视频 {args.id}（{kind}/{mode}/{resolution}/{duration}s）")
    pu.save_state(args.project, state)
    print(f"已更新 state.json（clip={args.id}）")


if __name__ == "__main__":
    main()
