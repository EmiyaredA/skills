"""向**已在运行**的 serve_review 推送 plan 草稿（POST /api/plan），不重启服务。

续作 / 备下一阶段时用本脚本；**禁止**为此再次 `serve_review --daemon`（旧服务仍占端口时会自增到新端口，用户链接会失效）。

  python push_plan.py --project "$P" --check          # 服务是否在跑，打印 URL
  python push_plan.py --project "$P" --plan plan.json

退出码：0=成功；1=服务未运行或请求失败；2=参数错误。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

import project_utils as pu


def _paths(project):
    review = pu.subdir(project, "review")
    return (
        os.path.join(review, "serve.pid"),
        os.path.join(review, "serve_url.txt"),
    )


def service_running(project):
    """返回 (running: bool, url: str|None, reason: str)。"""
    pid_file, url_file = _paths(project)
    url = None
    try:
        url = open(url_file, encoding="utf-8").read().strip()
    except OSError:
        pass
    try:
        pid = int(open(pid_file, encoding="utf-8").read().strip())
    except (OSError, ValueError):
        return False, url, "未找到 serve.pid（服务从未启动或已退出）"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, url, f"服务进程已不存在（PID {pid}）"
    except PermissionError:
        pass  # 进程存在但无权限发信号，仍视为在跑
    if not url:
        return False, None, f"进程 {pid} 在跑但未找到 serve_url.txt"
    return True, url, f"PID {pid}"


def post_plan(base_url, plan):
    url = base_url.rstrip("/") + "/api/plan"
    data = json.dumps(plan, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--plan", default=None, help="plan.json 路径（含 tasks 数组）")
    ap.add_argument("--check", action="store_true", help="仅检查服务是否在跑")
    args = ap.parse_args()

    project = os.path.abspath(args.project)
    pu.load_state(project)

    running, url, detail = service_running(project)
    if args.check:
        if running:
            print(f"SERVE_OK:{url}")
            print(f"服务运行中（{detail}）")
            raise SystemExit(0)
        print(f"SERVE_DOWN:{detail}")
        raise SystemExit(1)

    if not args.plan:
        print("缺少 --plan plan.json", file=sys.stderr)
        raise SystemExit(2)

    if not running:
        print(f"SERVE_DOWN:{detail}", file=sys.stderr)
        print("请先对本项目启动一次 serve_review --daemon；续作时不要重复启动。", file=sys.stderr)
        raise SystemExit(1)

    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)

    try:
        out = post_plan(url, plan)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"POST /api/plan 失败 HTTP {e.code}: {body}", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError as e:
        print(f"无法连接 {url}: {e.reason}", file=sys.stderr)
        raise SystemExit(1)

    if not out.get("ok"):
        print(f"推送失败: {out}", file=sys.stderr)
        raise SystemExit(1)

    n = out.get("prepared", len(plan.get("tasks") or []))
    print(f"PLAN_PUSHED:{n}")
    print(f"已推送 {n} 条草稿到 {url}（服务未重启）")


if __name__ == "__main__":
    main()
