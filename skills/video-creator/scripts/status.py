"""项目状态速览：各阶段已生成/已通过的资产（供 AI 续作前判断"做到哪一步了"）。

**state.json 是事实来源**：即使实时服务（serve_review）重启、其内存任务队列被清空，
已经生成好的资产仍然在 state.json 里。续作前务必用本脚本（或直接读 state.json）确认，
**只准备缺失的 / 下一阶段的任务，绝不重推已生成的资产**。

  python status.py --project /abs/项目目录        # 人类可读 + 末尾一段 JSON
  python status.py --project /abs/项目目录 --json   # 只输出 JSON（便于解析，无管道）
"""
import argparse
import json
import os

import project_utils as pu
import ensure_env as env

# (分类key, 显示名, 阶段) — 从 project_utils 单一来源派生
CATS = [(c["key"], c["label"], c["stage"]) for c in pu.PIPELINE_CATEGORIES]
STAGE_LABEL = pu.STAGE_LABEL


def _done(cat, it):
    if cat == "characters":
        return bool(it.get("three_view") or it.get("image"))
    if cat == "clips":
        # 样片或成片任一已生成即视为有产出
        return any((it.get(k) or {}).get("local_path") or (it.get(k) or {}).get("video_url")
                   for k in ("sample", "final"))
    if cat == "exports":
        return bool(it.get("video_url") or it.get("local_path"))
    return bool(it.get("image"))


def build(project):
    st = pu.load_state(project)

    stages = {}
    for cat, label, stg in CATS:
        s = stages.setdefault(stg, {"stage": stg, "label": STAGE_LABEL[stg], "categories": {}})
        lst = []
        for it in st.get(cat, []):
            review = it.get("review_decision", "")
            lst.append({"id": it["id"], "name": it.get("name", it["id"]),
                        "done": _done(cat, it), "review": review or "未评"})
        s["categories"][cat] = {"label": label, "items": lst}

    out = {"title": st.get("title", ""), "project": os.path.abspath(project),
           "has_key": pu.has_key(project), "stages": []}
    next_stage = None
    for stg in (1, 2, 3, 4):
        s = stages[stg]
        allit = [x for c in s["categories"].values() for x in c["items"]]
        s["count"] = len(allit)
        s["all_done"] = bool(allit) and all(x["done"] for x in allit)
        s["needs_revision"] = [x["id"] for x in allit if x["review"] == "需修改"]
        out["stages"].append(s)
        if next_stage is None and (not allit or not s["all_done"] or s["needs_revision"]):
            next_stage = stg
    out["next_stage"] = next_stage          # None = 全部阶段都已完成
    out["env"] = env.env_snapshot()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data = build(args.project)
    if not args.json:
        print(f"项目：{data['title']}  ({data['project']})")
        print(f"API Key：{'已配置' if data['has_key'] else '未配置'}")
        e = data.get("env") or {}
        print(f"环境：ffmpeg={'✓' if e.get('ffmpeg') else '✗'}  Pillow={'✓' if e.get('pillow') else '✗'}"
              + ("" if e.get("export_ready") else "  ⚠ 阶段4 导出需 ffmpeg"))
        for s in data["stages"]:
            flag = "✅完成" if s["all_done"] else ("◻空" if not s["count"] else "…进行中")
            print(f"\n阶段{s['stage']} {s['label']}  [{flag}]  共{s['count']}项")
            for cat, c in s["categories"].items():
                for x in c["items"]:
                    mark = "✓" if x["done"] else "✗待生成"
                    rev = f" · {x['review']}" if x["review"] not in ("未评", "通过") else ""
                    print(f"  - [{c['label']}] {x['id']} {x['name']} {mark}{rev}")
        ns = data["next_stage"]
        print("\n下一步：", f"阶段{ns}（{STAGE_LABEL[ns]}）尚未完成，只补这一阶段缺失/需修改的项" if ns
              else "全部阶段均已完成且通过。")
        print("\n--- JSON ---")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
