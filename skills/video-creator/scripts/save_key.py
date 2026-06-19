"""把用户在配置页提交的 API Key 写入项目级密钥文件 <project>/.sa_key（gitignored）。

SoWork 工作区里用户没有终端来 export，故由助手在收到用户提交的配置后调用本脚本落盘；
之后所有 gen_*.py 通过 project_utils.use_project_key 自动读取，无需每条命令重复 Key。

  python save_key.py --project ./drama --key sk-xxxx
  # 或从 stdin 读，避免 Key 出现在命令行/进程列表：
  echo "sk-xxxx" | python save_key.py --project ./drama --key -

平台已注入 SENSEAUDIO_API_KEY 环境变量时无需本脚本。
"""
import argparse
import sys

import project_utils as pu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--key", required=True, help="API Key；传 - 表示从 stdin 读取")
    args = ap.parse_args()

    key = sys.stdin.read().strip() if args.key == "-" else args.key.strip()
    if not key:
        raise SystemExit("空 Key")

    pu.save_project_key(args.project, key)
    print(f"已写入密钥文件：{pu.key_path(args.project)}（已加入 .gitignore，请勿提交）")


if __name__ == "__main__":
    main()
