"""向已在运行的 serve_review 推送 plan 草稿。详见 SKILL.md 助手协议。

  python push_plan.py --project "$P" --check
  python push_plan.py --project "$P" --plan plan.json [--force]
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

import project_utils as pu


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
    ap.add_argument("--plan", default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true", help="跳过重推保护，强制备稿")
    args = ap.parse_args()

    project = os.path.abspath(args.project)
    pu.load_state(project)

    running, url, detail = pu.service_running(project)
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
        raise SystemExit(1)

    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    if args.force:
        plan["force"] = True

    try:
        out = post_plan(url, plan)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"推送失败 HTTP {e.code}: {body}", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError as e:
        print(f"无法连接 {url}: {e.reason}", file=sys.stderr)
        raise SystemExit(1)

    if not out.get("ok"):
        print(f"推送失败: {out}", file=sys.stderr)
        raise SystemExit(1)

    prepared = out.get("prepared", 0)
    skipped = out.get("skipped", 0)
    print(f"PLAN_PUSHED:{prepared}")
    if skipped:
        print(f"PLAN_SKIPPED:{skipped}")
    print(f"已推送 {prepared} 条草稿到 {url}（跳过 {skipped} 条）")


if __name__ == "__main__":
    main()
