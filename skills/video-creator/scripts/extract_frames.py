"""从视频抽取首帧 / 末帧，用于「承接前置视频」或「续接后置视频」模式。

本地视频太大无法直接作为参考传给 API，改为抽取一帧作 first_frame / last_frame。

  python extract_frames.py --video prev.mp4 --out assets/refs --which last
  python extract_frames.py --video next.mp4 --out assets/refs --which first

需要系统已安装 ffmpeg。输出 PNG 路径会打印出来，可直接传给 gen_video.py 的
--first-frame / --last-frame。
"""
import argparse
import os
import shutil
import subprocess


def has_ffmpeg():
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def duration(video):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video])
    return float(out.decode().strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--which", default="last", choices=["first", "last"])
    args = ap.parse_args()

    if not has_ffmpeg():
        raise SystemExit("未检测到 ffmpeg/ffprobe，请先安装：brew install ffmpeg")
    if not os.path.exists(args.video):
        raise SystemExit(f"找不到视频：{args.video}")

    os.makedirs(args.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.video))[0]
    dest = os.path.join(args.out, f"{base}_{args.which}.png")

    if args.which == "first":
        ts = "0"
    else:
        ts = str(max(0.0, duration(args.video) - 0.05))

    subprocess.check_call([
        "ffmpeg", "-y", "-ss", ts, "-i", args.video,
        "-frames:v", "1", "-q:v", "2", dest],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(dest)


if __name__ == "__main__":
    main()
