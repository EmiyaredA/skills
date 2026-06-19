"""本地实时审核 + 生成进度服务。详见 SKILL.md；续作用 push_plan.py，勿重复 --daemon。

  python serve_review.py --project ./drama [--plan plan.json] [--port 8765] [--daemon] [--stop]
  python push_plan.py --project ./drama --plan plan.json
"""
import argparse
import json
import os
import signal
import sys
import threading

import project_utils as pu

from review.handlers import Handler
from review.queue import GenQueue
from review.state import ReviewState


def daemonize(logpath):
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    out = open(logpath or os.devnull, "a", buffering=1)
    os.dup2(out.fileno(), sys.stdout.fileno())
    os.dup2(out.fileno(), sys.stderr.fileno())
    nul = open(os.devnull, "r")
    os.dup2(nul.fileno(), sys.stdin.fileno())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--plan", default=None, help="首轮 plan JSON（待生成草稿）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    project = os.path.abspath(args.project)
    review_dir = pu.subdir(project, "review")
    os.makedirs(review_dir, exist_ok=True)
    pid_file, url_file = pu.review_paths(project)

    if args.stop:
        pu.stop_serve(project)
        return

    pu.load_state(project)
    try:
        os.remove(url_file)
    except OSError:
        pass

    if args.daemon and os.name == "posix":
        daemonize(os.path.join(review_dir, "serve.log"))

    pu.use_project_key(project)
    Handler.rs = ReviewState(project)
    Handler.gq = GenQueue(project, concurrency=args.concurrency)
    Handler.project = project

    if args.plan and os.path.exists(args.plan):
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
        Handler.gq.ingest_plan(plan, Handler.rs)

    from http.server import ThreadingHTTPServer

    port = args.port
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("找不到可用端口")
    Handler.server_ref = httpd

    url = f"http://127.0.0.1:{port}/"
    with open(url_file, "w", encoding="utf-8") as f:
        f.write(url)
    with open(pid_file, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    def _on_term(*_a):
        threading.Thread(target=httpd.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _on_term)

    if not args.no_open:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    print(f"SERVE:{url}")
    print(f"LINK:[打开实时审核页 ↗]({url})")
    print(f"实时审核服务已启动：{url}（并发 {args.concurrency} 路）", flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        for f in (pid_file, url_file):
            try:
                os.remove(f)
            except OSError:
                pass


if __name__ == "__main__":
    main()
