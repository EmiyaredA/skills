"""生成视频片段。样片（最省积分）/ 成片。

**参考图驱动**：以「分镜图 + 角色设定图」作参考生成镜头内容（不使用首/尾帧——首尾帧与参考素材不能混用）。
其它可选：
  纯文生视频    只给 --prompt
  承接前置视频  --prev-video <已托管URL>
  续接后置视频  --next-video <已托管URL>
  音频驱动      --audio voice.mp3

示例（样片，480p 最省；参考分镜图 + 角色）：
  python gen_video.py --project P --id clip_01 --sample \
      --prompt "林夏推开便利店门，回头一笑" \
      --reference assets/shots/shot_01.png --characters char_01 --duration 5

  --no-audio 关闭生成音轨。（--mock 仅 selftest 自检用，勿作交付）
"""
import argparse
import os
import sys

import sa_client as sa
import project_utils as pu


def derive_mode(refs, prev_v, next_v, audio):
    if prev_v:
        return "continue_prev"
    if next_v:
        return "continue_next"
    if refs:
        return "reference"
    if audio:
        return "audio_driven"
    return "text_to_video"


def _emit(msg, on_log=None):
    print(msg)
    if on_log:
        on_log(msg)


def run_video_generation(project, *, item_id, prompt, reference=None, characters=None,
                         prev_video=None, next_video=None, audio=None, shots=None,
                         duration=None, ratio=None, model=None, resolution=None,
                         sample=False, no_audio=False, watermark=None, mock=False,
                         on_log=None, on_progress=None):
    """生成视频并更新 state。成功返回 None，失败抛出 sa.APIError。"""
    state = pu.load_state(project)
    pu.use_project_key(project)
    if mock:
        _emit("⚠ MOCK：仅供 selftest 自检，写占位文件，切勿作为成品交付。", on_log)
    else:
        pu.require_key(project)

    cfg = state["config"]
    vcfg = cfg.get("video", {})
    ratio = ratio or cfg["ratio"]
    resolution = resolution or (vcfg.get("resolution_sample", "480p") if sample
                                else vcfg.get("resolution_final", "720p"))
    duration = duration if duration is not None else vcfg.get("duration_default", 5)
    generate_audio = (not no_audio) and vcfg.get("generate_audio", True)
    watermark = vcfg.get("watermark", True) if watermark is None else watermark
    refs = [r.strip() for r in reference.split(",")] if reference else []

    char_ids = pu.parse_id_list(characters)
    shot_ids = pu.parse_id_list(shots)

    if not refs:
        spec = {"characters": characters, "shots": shots, "references": refs}
        pu.resolve_generation_refs(state, "clips", spec)
        refs = spec.get("references") or []
        if not char_ids:
            char_ids = pu.parse_id_list(spec.get("characters"))
        if not shot_ids:
            shot_ids = pu.parse_id_list(spec.get("shots"))

    prompt_text = prompt
    if char_ids:
        anchor = pu.character_anchor(state, char_ids)
        if anchor:
            prompt_text = anchor + "本镜：" + prompt
    prompt_text = pu.apply_style(prompt_text, cfg.get("style"))

    mode = derive_mode(refs, prev_video, next_video, audio)
    cost = sa.estimate_video(resolution, duration)
    kind = "sample" if sample else "final"
    dest = os.path.join(pu.subdir(project, "output"), f"{item_id}_{kind}.mp4")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    _emit(f"模式={mode}  画质={resolution}  时长={duration}s  音轨={generate_audio}  参考成本~{cost:.2f}元", on_log)
    if refs:
        _emit(f"  ↳ 参考图 {len(refs)} 张；出场角色：{','.join(char_ids) or '(无)'}", on_log)

    shared = {
        "id": item_id, "mode": mode, "prompt": prompt,
        "model": model or vcfg.get("model", sa.DEFAULT_VIDEO_MODEL),
        "ratio": ratio, "shot_ids": shot_ids, "characters": char_ids,
        "inputs": {"reference": refs, "prev_video": prev_video,
                   "next_video": next_video, "audio": audio},
    }
    part = {"resolution": resolution, "duration": duration, "mode": mode,
            "cost_estimate": round(cost, 2), "status": "generating"}

    if mock:
        with open(dest, "wb") as f:
            f.write(b"MOCK_MP4_PLACEHOLDER")
        part.update(status="done", local_path=os.path.relpath(dest, project),
                    task_id="mock", video_url="")
        _emit(f"  ✓ (mock) {dest}", on_log)
    else:
        content = sa.build_video_content(
            prompt_text, reference_images=[pu.resolve_asset_path(project, r) for r in refs],
            prev_video=prev_video, next_video=next_video,
            audio=pu.resolve_asset_path(project, audio) if audio else None)
        task_id = sa.video_create(
            content, duration, resolution, ratio,
            model=model or vcfg.get("model", sa.DEFAULT_VIDEO_MODEL),
            generate_audio=generate_audio, watermark=watermark)
        part["task_id"] = task_id
        _emit(f"  任务已提交 task_id={task_id}，轮询中…", on_log)

        def show(status, progress):
            bar = f" {progress}%" if progress is not None else ""
            line = f"    状态：{status}{bar}"
            _emit(line, on_log)
            if on_progress and progress is not None:
                on_progress(progress, line)

        st = sa.video_poll(task_id, on_progress=show)
        sa.download(st["video_url"], dest)
        part.update(status="done", video_url=st["video_url"],
                    local_path=os.path.relpath(dest, project))
        _emit(f"  ✓ {dest}", on_log)

    def _apply(st):
        items = st.setdefault("clips", [])
        ex = pu.find(items, item_id)
        if not ex:
            ex = {"id": item_id}
            items.append(ex)
        ex.update(shared)
        ex[kind] = {**(ex.get(kind) or {}), **part}
        pu.log(st, f"生成视频 {item_id}（{kind}/{mode}/{resolution}/{duration}s）")

    pu.update_state(project, _apply)
    _emit(f"已更新 state.json（clip={item_id}）", on_log)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--reference", default=None)
    ap.add_argument("--characters", default=None)
    ap.add_argument("--prev-video", default=None)
    ap.add_argument("--next-video", default=None)
    ap.add_argument("--audio", default=None)
    ap.add_argument("--shots", default=None)
    ap.add_argument("--duration", type=int, default=None)
    ap.add_argument("--ratio", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--resolution", default=None, choices=["480p", "720p", "1080p"])
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--watermark", dest="watermark", action="store_true", default=None)
    ap.add_argument("--no-watermark", dest="watermark", action="store_false")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    run_video_generation(
        args.project, item_id=args.id, prompt=args.prompt, reference=args.reference,
        characters=args.characters, prev_video=args.prev_video, next_video=args.next_video,
        audio=args.audio, shots=args.shots, duration=args.duration, ratio=args.ratio,
        model=args.model, resolution=args.resolution, sample=args.sample,
        no_audio=args.no_audio, watermark=args.watermark, mock=args.mock,
    )


if __name__ == "__main__":
    try:
        main()
    except sa.APIError as e:
        print(f"sa_client.APIError: {e}", file=sys.stderr)
        raise SystemExit(1)
