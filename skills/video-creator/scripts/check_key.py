"""检查工作区是否已配置 SenseAudio API Key。真实生成前先跑这个。

  python check_key.py --project ./drama
退出码 0 = 有 Key 可生成；2 = 没有，须先让用户在配置页填写。
"""
import argparse

import project_utils as pu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    args = ap.parse_args()
    if args.project:
        pu.use_project_key(args.project)
    if pu.has_key(args.project):
        print("KEY_OK：已配置 API Key，可进行真实生成。")
        raise SystemExit(0)
    print("NO_KEY")
    print(pu.NO_KEY_MSG)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
