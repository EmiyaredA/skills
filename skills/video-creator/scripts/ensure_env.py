"""检查并安装 video-creator 可选环境依赖（ffmpeg、Pillow）。

助手在阶段4 导出前、或用户点「合成导出」失败时应先跑本脚本，缺啥装啥，不要只报错让用户自己装。

  python ensure_env.py --check                 # 只检查全部依赖
  python ensure_env.py --check --export        # 只检查导出所需（ffmpeg/ffprobe）
  python ensure_env.py --install               # 缺则自动安装全部
  python ensure_env.py --install --export      # 只安装导出所需
  python ensure_env.py --install --image       # 只安装图像拼贴所需（Pillow）

退出码：0 = 就绪；1 = 安装过程失败；2 = 仍缺依赖（未装 --install 或安装未成功）
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
REQ_FILE = os.path.join(SKILL_ROOT, "requirements.txt")

# 各依赖：检查函数名、安装说明（人工兜底）
DEPS = {
    "ffmpeg": {
        "label": "ffmpeg/ffprobe（阶段4 成片导出拼接）",
        "group": "export",
    },
    "pillow": {
        "label": "Pillow（阶段2 多参考图拼贴，可选）",
        "group": "image",
    },
}


def has_ffmpeg():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def has_pillow():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def check_status(names):
    """返回 {name: bool}。"""
    probes = {"ffmpeg": has_ffmpeg, "pillow": has_pillow}
    return {n: probes[n]() for n in names}


def _run_install(cmd, label):
    print(f"  → {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, check=False)
    except FileNotFoundError as e:
        return False, f"{label}：找不到命令 {cmd[0]}（{e}）"
    if r.returncode != 0:
        return False, f"{label}：命令退出码 {r.returncode}"
    return True, ""


def install_ffmpeg():
    if has_ffmpeg():
        return True, "ffmpeg 已就绪"
    system = platform.system()
    if system == "Darwin":
        if not shutil.which("brew"):
            return False, "未找到 Homebrew。请先安装 https://brew.sh 后重试，或手动：`brew install ffmpeg`"
        ok, err = _run_install(["brew", "install", "ffmpeg"], "brew install ffmpeg")
        if ok and has_ffmpeg():
            return True, "已通过 Homebrew 安装 ffmpeg"
        return False, err or "brew install ffmpeg 完成但仍找不到 ffmpeg/ffprobe"
    if system == "Linux":
        candidates = []
        if shutil.which("apt-get"):
            candidates.append(["apt-get", "install", "-y", "ffmpeg"])
            if shutil.which("sudo"):
                candidates.append(["sudo", "apt-get", "install", "-y", "ffmpeg"])
        if shutil.which("dnf"):
            candidates.append(["dnf", "install", "-y", "ffmpeg"])
            if shutil.which("sudo"):
                candidates.append(["sudo", "dnf", "install", "-y", "ffmpeg"])
        if shutil.which("yum"):
            candidates.append(["yum", "install", "-y", "ffmpeg"])
        if shutil.which("pacman"):
            candidates.append(["pacman", "-S", "--noconfirm", "ffmpeg"])
        for cmd in candidates:
            ok, err = _run_install(cmd, " ".join(cmd))
            if ok and has_ffmpeg():
                return True, f"已安装 ffmpeg（{' '.join(cmd)}）"
        if not candidates:
            return False, "Linux 上未识别包管理器，请手动安装 ffmpeg（如 apt install ffmpeg）"
        return False, err or "包管理器安装 ffmpeg 失败，请手动安装"
    return False, f"暂不支持在 {system} 上自动安装 ffmpeg，请查阅官方文档手动安装"


def install_pillow():
    if has_pillow():
        return True, "Pillow 已就绪"
    cmd = [sys.executable, "-m", "pip", "install", "-q", "Pillow>=9"]
    if os.path.isfile(REQ_FILE):
        cmd = [sys.executable, "-m", "pip", "install", "-q", "-r", REQ_FILE]
    ok, err = _run_install(cmd, "pip install Pillow")
    if ok and has_pillow():
        return True, "已通过 pip 安装 Pillow"
    return False, err or "pip install Pillow 失败"


def resolve_deps(export=False, image=False):
    names = []
    if export:
        names.append("ffmpeg")
    if image:
        names.append("pillow")
    return names


def ensure(names, install=False):
    """检查（并可选安装）依赖。返回 (ok, status_dict, messages)。"""
    msgs = []
    status = check_status(names)
    missing = [n for n, ok in status.items() if not ok]
    if not missing:
        return True, status, ["ENV_OK：全部依赖已就绪"]

    if not install:
        for n in missing:
            msgs.append(f"MISSING {n}：{DEPS[n]['label']}")
        return False, status, msgs

    installers = {"ffmpeg": install_ffmpeg, "pillow": install_pillow}
    for n in missing:
        print(f"正在安装 {DEPS[n]['label']}…")
        ok, msg = installers[n]()
        msgs.append(msg)
        if not ok:
            status = check_status(names)
            still = [x for x, v in status.items() if not v]
            if still:
                msgs.append(f"仍缺：{', '.join(still)}")
            return False, status, msgs

    status = check_status(names)
    still = [n for n, ok in status.items() if not ok]
    if still:
        msgs.append(f"安装后仍缺：{', '.join(still)}")
        return False, status, msgs
    msgs.append("ENV_OK：依赖已安装并就绪")
    return True, status, msgs


def env_snapshot():
    """供 status.py 等读取的简要环境快照。"""
    st = check_status(["ffmpeg", "pillow"])
    return {
        "ffmpeg": st["ffmpeg"],
        "pillow": st["pillow"],
        "export_ready": st["ffmpeg"],
    }


def main():
    ap = argparse.ArgumentParser(description="检查/安装 video-creator 环境依赖")
    ap.add_argument("--check", action="store_true", help="只检查，不安装")
    ap.add_argument("--install", action="store_true", help="缺少则尝试自动安装")
    ap.add_argument("--export", action="store_true", help="只处理导出依赖（ffmpeg）")
    ap.add_argument("--image", action="store_true", help="只处理图像依赖（Pillow）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()
    if not args.check and not args.install:
        args.check = True

    names = resolve_deps(export=args.export, image=args.image)
    ok, status, msgs = ensure(names, install=args.install)

    if args.json:
        import json
        print(json.dumps({"ok": ok, "status": status, "messages": msgs}, ensure_ascii=False))
    else:
        for m in msgs:
            print(m)

    if ok:
        raise SystemExit(0)
    raise SystemExit(1 if args.install else 2)


if __name__ == "__main__":
    main()
