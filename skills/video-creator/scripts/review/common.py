"""serve_review 共享常量与工具。"""
import os
import re
import sys
import urllib.parse

import sa_client as sa
import project_utils as pu

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_ROOT = os.path.dirname(HERE)
PCT = re.compile(r"(\d{1,3})%")
MAX_RETRIES = 3

CATEGORIES = [{"key": c["key"], "label": c["label"], "icon": c["icon"], "kind": c["kind"]}
              for c in pu.PIPELINE_CATEGORIES]
STAGE_OF = pu.STAGE_OF
STAGES = pu.STAGES
RATIOS = pu.RATIOS
RESOLUTIONS = pu.RESOLUTIONS
EDITABLE = ("prompt", "model", "ratio", "resolution", "duration", "sample")


def media_url(rel):
    if not rel:
        return None
    if rel.startswith(("http://", "https://")):
        return rel
    return "/media?path=" + urllib.parse.quote(rel)


def load_index_html():
    path = os.path.join(SKILL_ROOT, "templates", "review.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


def est_cost(key, spec):
    try:
        if key == "clips":
            return round(sa.estimate_video(spec.get("resolution") or "480p", int(spec.get("duration") or 5)), 2)
        if key in ("characters", "scenes", "shots"):
            n = len(pu.parse_id_list(spec.get("views"))) if spec.get("views") else 1
            return round(sa.estimate_image(spec.get("model") or sa.DEFAULT_IMAGE_MODEL) * n, 2)
    except Exception:
        return None
    return None


def build_export_cmd(project, spec):
    """导出拼接 → concat_clips.py 命令行。"""
    py = sys.executable or "python3"
    iid = spec.get("id")
    order = spec.get("order")
    order = order if isinstance(order, str) else ",".join(order or [])
    cmd = [py, os.path.join(HERE, "concat_clips.py"), "--project", project,
           "--id", iid, "--ids", order]
    if spec.get("title"):
        cmd += ["--title", spec["title"]]
    if spec.get("ratio"):
        cmd += ["--ratio", spec["ratio"]]
    return cmd


def export_fail_message(tail):
    """从 export 子进程输出提取可读错误。"""
    if not tail:
        return ""
    if "copyright" in tail.lower() or "版权" in tail:
        return sa.format_video_error(
            tail.split("error_message")[-1] if "error_message" in tail else tail[-400:]
        )
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if line.startswith("❌"):
            return line.lstrip("❌").strip()
    return tail.strip()[-400:]
