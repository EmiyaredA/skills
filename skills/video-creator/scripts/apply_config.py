"""把一个配置 JSON 应用到已存在的项目（一般用户在实时应用「设置」里改配置，本脚本供命令行/调试/预设用）。

  python apply_config.py --project ./drama --config ./preset.json

api_key 字段会被忽略（不落盘）。同样可在 init_project.py --config 时一并应用。
"""
import argparse
import json

import project_utils as pu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--config", required=True, help="配置 JSON 路径")
    args = ap.parse_args()

    state = pu.load_state(args.project)
    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("api_key"):
        print("注意：检测到 api_key，已忽略（不写入文件）。请改用环境变量：")
        print("  export SENSEAUDIO_API_KEY=你的key")
    merged = pu.apply_config(state, cfg)
    pu.log(state, "应用配置 JSON")
    pu.save_state(args.project, state)
    print("已更新 config：")
    print(json.dumps(merged, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
