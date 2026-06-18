"""把一张 base64 data URI 参考图落盘到项目 assets/refs/（实时应用上传参考图时由 serve_review 内部直接处理；
本脚本供命令行/调试单独落盘用），再把得到的路径用作 gen_image/gen_video 的 --reference。

  # data URI 从 stdin 读（推荐，避免命令行过长）
  printf 'data:image/jpeg;base64,...' | python save_ref.py --project ./drama --name char_02_ref --datauri -
  # 或直接传参
  python save_ref.py --project ./drama --name scene_ref --datauri 'data:image/jpeg;base64,...'

打印写入的相对路径（相对项目目录），可直接作为 --reference 传入。
"""
import argparse
import base64
import os
import sys

import project_utils as pu

EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--name", required=True, help="文件名（不含扩展名），如 char_02_ref")
    ap.add_argument("--datauri", required=True, help="data URI；传 - 从 stdin 读")
    args = ap.parse_args()

    uri = sys.stdin.read().strip() if args.datauri == "-" else args.datauri.strip()
    if not uri.startswith("data:"):
        raise SystemExit("不是 data URI（应以 data: 开头）")
    header, _, b64 = uri.partition(",")
    mime = header[5:].split(";")[0]
    ext = EXT.get(mime, ".png")
    outdir = os.path.join(args.project, "assets", "refs")
    os.makedirs(outdir, exist_ok=True)
    dest = os.path.join(outdir, args.name + ext)
    with open(dest, "wb") as f:
        f.write(base64.b64decode(b64))
    rel = os.path.relpath(dest, args.project)
    print(rel)


if __name__ == "__main__":
    main()
