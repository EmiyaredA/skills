"""初始化短剧项目：创建目录结构与 state.json。

两种用法：
  # ① 显式项目目录
  python init_project.py --project ./my-drama --title "深夜便利店" --ratio 9:16

  # ② 在「总工作目录」下自动新建一个带唯一 id 的子目录作为本轮项目（隔离不同对话，推荐）
  python init_project.py --parent /abs/总工作目录 --title "深夜便利店"
  # → 在 <总工作目录>/<标题slug>_<时间>_<随机> 下初始化，并打印 PROJECT:<绝对路径>（后续命令都用它）
"""
import argparse
import json
import os
import re
import time
import uuid

import project_utils as pu


def _unique_subdir(parent, title):
    slug = re.sub(r"[^0-9A-Za-z一-鿿]+", "_", (title or "drama")).strip("_")[:24] or "drama"
    name = f"{slug}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
    return os.path.join(parent, name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None, help="项目目录（显式指定本轮项目根）")
    ap.add_argument("--parent", default=None,
                    help="总工作目录：在其下自动新建唯一子目录作为本轮项目（隔离不同对话）")
    ap.add_argument("--title", default="", help="作品标题")
    ap.add_argument("--ratio", default="16:9", choices=["16:9", "9:16", "4:3", "3:4", "1:1"])
    ap.add_argument("--style", default="", help="整体视觉风格，如『写实电影感』")
    ap.add_argument("--config", default=None, help="可选：一个配置 JSON（预设），应用到 config；一般不用，配置在应用「设置」里改")
    args = ap.parse_args()

    if args.project:
        project = os.path.abspath(args.project)
    elif args.parent:
        project = os.path.abspath(_unique_subdir(args.parent, args.title))   # 每轮对话唯一，互相隔离
    else:
        ap.error("需要 --project 或 --parent 其一")

    pu.ensure_dirs(project)

    path = pu.state_path(project)
    if os.path.exists(path):
        print(f"已存在 {path}，跳过初始化。")
        print(f"PROJECT:{project}")
        return
    state = pu.default_state(args.title)
    state["config"]["ratio"] = args.ratio
    state["config"]["style"] = args.style
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            pu.apply_config(state, json.load(f))
        print(f"已应用配置：{args.config}")
    pu.log(state, "项目初始化")
    pu.save_state(project, state)
    print(f"已初始化项目：{project}")
    print(f"  state: {path}")
    print(f"  画幅: {state['config']['ratio']}  风格: {state['config']['style'] or '(未设置)'}")
    print(f"PROJECT:{project}")   # 后续 serve_review/gen_* 都用这个绝对路径


if __name__ == "__main__":
    main()
