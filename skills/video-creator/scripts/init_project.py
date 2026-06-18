"""初始化短剧项目：创建目录结构与 state.json。

用法：
  python init_project.py --project ./my-drama --title "深夜便利店" --ratio 9:16
"""
import argparse
import json
import os

import project_utils as pu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="项目目录")
    ap.add_argument("--title", default="", help="作品标题")
    ap.add_argument("--ratio", default="9:16", choices=["16:9", "9:16", "4:3", "3:4", "1:1"])
    ap.add_argument("--style", default="", help="整体视觉风格，如『写实电影感』")
    ap.add_argument("--config", default=None, help="可选：一个配置 JSON（预设），应用到 config；一般不用，配置在应用「设置」里改")
    args = ap.parse_args()

    pu.ensure_dirs(args.project)

    path = pu.state_path(args.project)
    if os.path.exists(path):
        print(f"已存在 {path}，跳过初始化。")
        return
    state = pu.default_state(args.title)
    state["config"]["ratio"] = args.ratio
    state["config"]["style"] = args.style
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            pu.apply_config(state, json.load(f))
        print(f"已应用配置：{args.config}")
    pu.log(state, "项目初始化")
    pu.save_state(args.project, state)
    print(f"已初始化项目：{args.project}")
    print(f"  state: {path}")
    print(f"  画幅: {state['config']['ratio']}  风格: {state['config']['style'] or '(未设置)'}")


if __name__ == "__main__":
    main()
