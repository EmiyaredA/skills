"""审核页 state.json → API payload 转换。"""
import os

import project_utils as pu

from review.common import CATEGORIES, STAGES, media_url


class ReviewState:
    def __init__(self, project):
        self.project = project

    def load(self):
        return pu.load_state(self.project)

    def save(self, state):
        pu.save_state(self.project, state)

    def _char_item(self, c):
        tv = c.get("three_view") or {}
        media = [{"type": "image", "src": media_url(p), "name": os.path.basename(p), "caption": v}
                 for v, p in tv.items() if p]
        if not media and c.get("image"):
            media = [{"type": "image", "src": media_url(c["image"]),
                      "name": os.path.basename(c["image"]), "caption": ""}]
        return {"id": c["id"], "title": c.get("name") or c["id"],
                "meta": (c.get("gender") or ""), "prompt": c.get("prompt", ""),
                "model": c.get("model", ""), "ratio": c.get("ratio", "16:9"),
                "references": pu.get_refs(c, "characters"),
                "media": media, "decision": c.get("review_decision", "通过"),
                "note": c.get("review_note", ""), "status": c.get("status", "draft")}

    def _simple_item(self, it, category):
        src = it.get("image")
        media = [{"type": "image", "src": media_url(src),
                  "name": os.path.basename(src) if src else "", "caption": ""}] if src else []
        return {"id": it["id"], "title": it.get("name") or it["id"],
                "meta": it.get("scene_id", ""), "prompt": it.get("prompt", ""),
                "model": it.get("model", ""), "ratio": it.get("ratio", ""),
                "references": pu.get_refs(it, category),
                "media": media, "decision": it.get("review_decision", "通过"),
                "note": it.get("review_note", ""), "status": it.get("status", "draft")}

    def _clip_item(self, cl):
        def part(kind):
            p = cl.get(kind) or {}
            src = p.get("video_url") or p.get("local_path")
            media = [{"type": "video", "src": media_url(src),
                      "name": os.path.basename(src) if src and not src.startswith("http")
                      else f"{cl['id']}_{kind}.mp4",
                      "caption": f"{kind} {p.get('resolution', '')}"}] if src else []
            return {"media": media, "status": p.get("status", "draft"),
                    "resolution": p.get("resolution", ""), "duration": p.get("duration", "")}
        dur = (cl.get("final") or cl.get("sample") or {}).get("duration", 5)
        return {"id": cl["id"], "title": cl["id"], "meta": cl.get("mode", ""),
                "prompt": cl.get("prompt", ""), "model": cl.get("model", ""),
                "duration": dur, "ratio": cl.get("ratio", ""),
                "references": pu.get_refs(cl, "clips"),
                "sample": part("sample"), "final": part("final"),
                "decision": cl.get("review_decision", "通过"),
                "note": cl.get("review_note", ""), "status": cl.get("status", "draft")}

    def _export_item(self, e):
        src = e.get("local_path") or e.get("video_url")
        media = [{"type": "video", "src": media_url(src),
                  "name": os.path.basename(src) if src and not src.startswith("http")
                  else (e["id"] + ".mp4"),
                  "caption": "成片"}] if src else []
        order = e.get("order") or []
        return {"id": e["id"], "title": e.get("title") or e["id"],
                "meta": f"{len(order)} 段拼接", "order": order,
                "prompt": "", "model": "", "ratio": e.get("ratio", ""), "references": [],
                "media": media, "decision": e.get("review_decision", "通过"),
                "note": e.get("review_note", ""), "status": e.get("status", "draft")}

    def items(self, state, key):
        if key == "characters":
            return [self._char_item(c) for c in state.get("characters", [])]
        if key == "scenes":
            return [self._simple_item(s, "scenes") for s in state.get("scenes", [])]
        if key == "shots":
            return [self._simple_item(s, "shots") for s in state.get("shots", [])]
        if key == "clips":
            return [self._clip_item(c) for c in state.get("clips", [])]
        if key == "exports":
            return [self._export_item(e) for e in state.get("exports", [])]
        return []

    def payload(self):
        import sa_client as sa
        state = self.load()
        cfg = pu.default_config()
        pu.deep_merge(cfg, state.get("config") or {})
        cats, items = [], {}
        for c in CATEGORIES:
            its = self.items(state, c["key"])
            items[c["key"]] = its
            cats.append({**c, "count": len(its)})
        img_models = [{"id": m, "price": p} for m, p in sa.IMAGE_PRICE.items()]
        vid_models = [m for m in dict.fromkeys([cfg.get("video", {}).get("model"), sa.DEFAULT_VIDEO_MODEL]) if m]
        return {
            "title": state.get("title") or "短剧项目",
            "project": self.project, "config": cfg, "categories": cats, "items": items,
            "stages": STAGES,
            "options": {"image_models": img_models, "video_models": vid_models,
                        "ratios": pu.RATIOS, "resolutions": pu.RESOLUTIONS},
            "has_key": pu.has_key(self.project),
        }
