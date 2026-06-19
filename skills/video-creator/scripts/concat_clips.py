"""把已生成的视频 clip 按指定顺序拼接成一条成片导出（需要 ffmpeg）。

AI 按剧情把要拼接的 clip 排好顺序，用户在应用「成片导出」里点「合成导出」触发本脚本。
先把每段归一化到统一画幅/帧率/音轨（兼容样片 480p 与成片 1080p 混排），再无损拼接。

  python concat_clips.py --project P --id export_01 --ids clip_01,clip_02,clip_03 --title 成片

缺 ffmpeg 时以退出码 2 退出并提示安装（不产出半成品）。
"""
import argparse
import os
import shutil
import subprocess

import ensure_env as env
import project_utils as pu

# 各画幅的导出尺寸（默认 16:9）
RATIO_DIMS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080),
              "4:3": (1440, 1080), "3:4": (1080, 1440)}


def has_ffmpeg():
    return env.has_ffmpeg()


def has_audio(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True)
        return bool(out.stdout.strip())
    except Exception:
        return False


def run_ff(cmd, what):
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        tail = (p.stderr or "").strip()[-800:]
        print(f"❌ ffmpeg {what} 失败：\n{tail}")
        raise SystemExit(1)


def normalize(src, dst, w, h):
    """把单段视频缩放并居中补边到统一 w×h、30fps、AAC 立体声（无音轨则补静音），便于无损拼接。"""
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p")
    if has_audio(src):
        cmd = ["ffmpeg", "-y", "-i", src, "-vf", vf,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", dst]
    else:
        cmd = ["ffmpeg", "-y", "-i", src,
               "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-vf", vf, "-shortest", "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-c:a", "aac", "-b:a", "128k", dst]
    run_ff(cmd, "归一化")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--id", required=True, help="本次导出的 id（输出 output/<id>.mp4）")
    ap.add_argument("--ids", required=True, help="要拼接的 clip id，按播放顺序逗号分隔")
    ap.add_argument("--title", default="")
    ap.add_argument("--ratio", default=None, help="覆盖项目画幅（默认取 config.ratio）")
    args = ap.parse_args()

    state = pu.load_state(args.project)
    if not has_ffmpeg():
        print("未检测到 ffmpeg/ffprobe，尝试自动安装…", flush=True)
        ok, _, msgs = env.ensure(["ffmpeg"], install=True)
        for m in msgs:
            print(f"  {m}", flush=True)
        if not ok:
            print("❌ 无法拼接导出：ffmpeg 仍未就绪。助手应运行 "
                  "`python scripts/ensure_env.py --install --export` 后重试。")
            raise SystemExit(2)

    clip_ids = [c.strip() for c in args.ids.split(",") if c.strip()]
    if not clip_ids:
        print("❌ 未指定要拼接的 clip（--ids 为空）。")
        raise SystemExit(2)

    # 解析每个 clip 的本地视频文件（优先成片，回退样片）
    paths, missing = [], []
    for cid in clip_ids:
        cl = pu.find(state.get("clips", []), cid) or {}
        part = cl.get("final") or cl.get("sample") or {}
        lp = part.get("local_path")
        full = os.path.join(args.project, lp) if lp else None
        if full and os.path.exists(full):
            paths.append((cid, full))
        else:
            missing.append(cid)
    if missing:
        print(f"❌ 这些 clip 还没生成或找不到视频文件：{','.join(missing)}。请先在阶段3 生成它们再导出。")
        raise SystemExit(2)

    ratio = args.ratio or state.get("config", {}).get("ratio", "16:9")
    w, h = RATIO_DIMS.get(ratio, (1080, 1920))

    outdir = pu.subdir(args.project, "output")
    os.makedirs(outdir, exist_ok=True)
    tmpdir = os.path.join(outdir, f".tmp_{args.id}")
    os.makedirs(tmpdir, exist_ok=True)
    out = os.path.join(outdir, f"{args.id}.mp4")
    n = len(paths)
    print(f"开始导出：{n} 段 · {ratio}（{w}x{h}）· 顺序 {'→'.join(c for c, _ in paths)}", flush=True)
    try:
        norm_paths = []
        for i, (cid, src) in enumerate(paths):
            dst = os.path.join(tmpdir, f"{i:03d}.mp4")
            normalize(src, dst, w, h)
            norm_paths.append(dst)
            print(f"  ✓ 归一化 {cid}（{i + 1}/{n}） {int((i + 1) / n * 85)}%", flush=True)
        listfile = os.path.join(tmpdir, "list.txt")
        with open(listfile, "w", encoding="utf-8") as f:
            for p in norm_paths:
                f.write(f"file '{p}'\n")
        print(f"  拼接 {n} 段… 92%", flush=True)
        run_ff(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
                "-c", "copy", out], "拼接")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    rel = os.path.relpath(out, args.project)
    record = {"id": args.id, "title": args.title or args.id, "order": clip_ids,
              "ratio": ratio, "local_path": rel, "status": "done"}

    def _apply(st):
        items = st.setdefault("exports", [])
        ex = pu.find(items, args.id)
        if ex:
            ex.update(record)
        else:
            items.append(record)
        pu.log(st, f"导出成片 {args.id}：按序拼接 {n} 段 [{','.join(clip_ids)}]")
    pu.update_state(args.project, _apply)
    print(f"  ✓ 导出完成：{out} 100%", flush=True)
    print(f"已更新 state.json（export={args.id}）")


if __name__ == "__main__":
    main()
