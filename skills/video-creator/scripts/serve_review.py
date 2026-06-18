"""本地实时审核 + 生成进度服务：左侧分类侧边栏 + 右侧卡片，**先开前端，再边生成边看进度**。

本服务是整套 skill 的**唯一前端**，**活的**：
- 助手把「生成计划」(plan.json) 交给本服务并**先把网页打开**；服务用后台 worker 池**并行**生成（默认 4 路），
  每个资产立刻是一张占位卡片，带状态（排队/生成中%/完成/失败）；顶部一条总进度。
- 用户在页面上看进度；完成的卡片可立刻改提示词/参考图/模型/设置并「重新生成」，失败的可「重试」；
  点侧边栏「设置」随时改全局配置/Key、即时落盘生效。
- 用户点「继续 / 重做这一批」→ 服务把结果写入 review/review_result.json 并自动退出
  → 后台任务结束会重新唤起助手，助手读 state.json + review_result.json 决定下一步。

接口：
  GET  /                 单页应用（侧边栏 + 卡片 + 进度 + 设置面板）
  GET  /api/state        全量状态：分类、各分类条目、配置、可选模型/画幅/分辨率
  GET  /api/tasks        生成任务队列与进度（前端轮询）
  GET  /media?path=rel   流式返回项目内的图片/音频/视频（带防越权校验）
  POST /api/config       深合并配置并落盘（实时生效）
  POST /api/decision     保存某条目的「通过/需修改」+ 意见
  POST /api/regenerate   按本条目编辑后的提示词/参考图/模型/设置重新生成（入队）
  POST /api/retry        用原始计划参数重试某失败任务（入队）
  POST /api/stop         停止：取消所有排队任务（当前任务跑完即停）
  POST /api/finish       记录「继续/重做」动作 → 写 review_result.json → 关闭服务

  python serve_review.py --project ./drama [--plan plan.json] [--port 8765] [--no-open]

plan.json 形如：{"tasks":[
  {"category":"characters","id":"char_01","name":"林夏","prompt":"...","gender":"女","views":"front,side,back","sample":true},
  {"category":"scenes","id":"scene_01","name":"便利店","prompt":"..."},
  {"category":"shots","id":"shot_01","prompt":"...","characters":"char_01","scene":"scene_01"},
  {"category":"clips","id":"clip_01","prompt":"...","first_frame":"assets/shots/shot_01.png","resolution":"480p","duration":5,"sample":true}
]}
"""
import argparse
import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sa_client as sa
import project_utils as pu

HERE = os.path.dirname(os.path.abspath(__file__))
RATIOS = ["9:16", "16:9", "4:3", "3:4", "1:1"]
RESOLUTIONS = ["480p", "720p", "1080p"]
PCT = re.compile(r"(\d{1,3})%")

CATEGORIES = [
    {"key": "characters", "label": "角色三视图", "icon": "user", "kind": "image"},
    {"key": "scenes", "label": "场景", "icon": "photo", "kind": "image"},
    {"key": "shots", "label": "分镜机位", "icon": "clapperboard", "kind": "image"},
    {"key": "clips", "label": "视频片段", "icon": "movie", "kind": "video"},
    {"key": "voices", "label": "语音配音", "icon": "microphone", "kind": "voice"},
]
EXT_BY_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
# 用户在卡片上可直接改、并覆盖原始计划参数的字段
EDITABLE = ("prompt", "model", "ratio", "resolution", "duration", "sample", "voice_id", "text")


def _media_url(rel):
    if not rel:
        return None
    if rel.startswith(("http://", "https://")):
        return rel
    return "/media?path=" + urllib.parse.quote(rel)


def _ref_list(*vals):
    out = []
    for v in vals:
        for r in (v if isinstance(v, list) else [v]):
            if r and r not in out:
                out.append(r)
    return out


def save_datauri(project, name, uri):
    """把上传的 data URI 落盘到 assets/refs/，返回相对路径。"""
    if not uri.startswith("data:"):
        return None
    header, _, b64 = uri.partition(",")
    mime = header[5:].split(";")[0]
    ext = EXT_BY_MIME.get(mime, ".png")
    outdir = pu.subdir(project, "refs")
    os.makedirs(outdir, exist_ok=True)
    dest = os.path.join(outdir, name + ext)
    with open(dest, "wb") as f:
        f.write(base64.b64decode(b64))
    return os.path.relpath(dest, project)


def est_cost(key, spec):
    try:
        if key == "clips":
            return round(sa.estimate_video(spec.get("resolution") or "480p", int(spec.get("duration") or 5)), 2)
        if key in ("characters", "scenes", "shots"):
            n = len((spec.get("views") or "").split(",")) if spec.get("views") else 1
            return round(sa.estimate_image(spec.get("model") or sa.DEFAULT_VIDEO_MODEL) * n, 2)
    except Exception:
        pass
    return 0.0


def build_gen_cmd(project, key, spec):
    """把一条生成 spec 翻译成对应 gen_*.py 命令行（计划/重生成/重试共用）。"""
    py = sys.executable or "python3"
    iid = spec.get("id")
    prompt = spec.get("prompt") or ""
    refs = spec.get("references") or []
    model = spec.get("model") or None
    if key in ("characters", "scenes", "shots"):
        typ = {"characters": "character", "scenes": "scene", "shots": "shot"}[key]
        cmd = [py, os.path.join(HERE, "gen_image.py"), "--project", project,
               "--type", typ, "--id", iid, "--prompt", prompt]
        if spec.get("name"):
            cmd += ["--name", spec["name"]]
        if spec.get("ratio"):
            cmd += ["--ratio", spec["ratio"]]
        if model:
            cmd += ["--model", model]
        if spec.get("sample"):
            cmd += ["--sample"]
        if key == "characters":
            if spec.get("gender"):
                cmd += ["--gender", spec["gender"]]
            if spec.get("views"):
                cmd += ["--views", spec["views"]]
            if spec.get("style_ref"):
                cmd += ["--style-ref", spec["style_ref"]]
        if key == "shots":
            if spec.get("characters"):
                cmd += ["--characters", spec["characters"]]
            if spec.get("scene"):
                cmd += ["--scene", spec["scene"]]
        if refs:
            cmd += ["--reference", refs[0]]   # 图像 API 仅接受单张参考图
        return cmd
    if key == "clips":
        cmd = [py, os.path.join(HERE, "gen_video.py"), "--project", project,
               "--id", iid, "--prompt", prompt]
        if model:
            cmd += ["--model", model]
        if spec.get("resolution"):
            cmd += ["--resolution", spec["resolution"]]
        if spec.get("duration"):
            cmd += ["--duration", str(int(spec["duration"]))]
        if spec.get("ratio"):
            cmd += ["--ratio", spec["ratio"]]
        if spec.get("sample"):
            cmd += ["--sample"]
        if spec.get("characters"):
            cmd += ["--characters", spec["characters"]]
        if spec.get("scene"):
            cmd += ["--scene", spec["scene"]]
        if spec.get("first_frame"):
            cmd += ["--first-frame", spec["first_frame"]]
        if spec.get("last_frame"):
            cmd += ["--last-frame", spec["last_frame"]]
        if spec.get("prev_video"):
            cmd += ["--prev-video", spec["prev_video"]]
        if spec.get("next_video"):
            cmd += ["--next-video", spec["next_video"]]
        if spec.get("audio"):
            cmd += ["--audio", spec["audio"]]
        if refs:
            cmd += ["--reference", ",".join(refs)]
        return cmd
    if key == "voices":
        cmd = [py, os.path.join(HERE, "gen_voice.py"), "--project", project,
               "--character", iid, "--text", spec.get("text") or ""]
        if spec.get("voice_id"):
            cmd += ["--voice-id", spec["voice_id"]]
        return cmd
    return None


class GenQueue:
    """生成任务队列 + worker 线程池（默认 4 路并行）。记录每条任务状态/进度，供前端轮询。"""

    def __init__(self, project, concurrency=4):
        self.project = project
        self.concurrency = max(1, int(concurrency))
        self.lock = threading.Lock()
        self.tasks = []          # 公开任务列表
        self.specs = {}          # key -> 最近一次完整 spec（用于重试保留原始参数）
        self.seq = 0
        self._stop = False
        self.workers = []        # 并行 worker 线程池

    def _key(self, spec):
        return f"{spec['category']}::{spec['id']}"

    def enqueue(self, spec):
        with self.lock:
            k = self._key(spec)
            self.specs[k] = dict(spec)
            self.seq += 1
            t = {"task_id": self.seq, "category": spec["category"], "item_id": spec["id"],
                 "label": spec.get("name") or spec["id"], "status": "queued",
                 "progress": None, "message": "", "cost": est_cost(spec["category"], spec)}
            # 同一资产若已有结束态任务，移除旧的，避免列表堆积
            self.tasks = [x for x in self.tasks
                          if not (x["category"] == spec["category"] and x["item_id"] == spec["id"]
                                  and x["status"] in ("done", "failed", "canceled"))]
            self.tasks.append(t)
        self._ensure_workers()
        return t

    def retry(self, category, iid):
        k = f"{category}::{iid}"
        spec = self.specs.get(k)
        if spec:
            return self.enqueue(dict(spec))
        return None

    def stop(self):
        with self.lock:
            self._stop = True
            for t in self.tasks:
                if t["status"] == "queued":
                    t["status"] = "canceled"

    def _ensure_workers(self):
        """按并发上限补足 worker（多个 worker 并行从队列取任务）。"""
        self._stop = False
        with self.lock:
            self.workers = [w for w in self.workers if w.is_alive()]
            queued = sum(1 for t in self.tasks if t["status"] == "queued")
            need = min(self.concurrency, queued) - len(self.workers)
        for _ in range(max(0, need)):
            w = threading.Thread(target=self._run, daemon=True)
            with self.lock:
                self.workers.append(w)
            w.start()

    def _run(self):
        while True:
            with self.lock:
                if self._stop:
                    break
                nxt = next((t for t in self.tasks if t["status"] == "queued"), None)
                if not nxt:
                    break
                nxt["status"] = "running"
                nxt["progress"] = None
                spec = self.specs[f"{nxt['category']}::{nxt['item_id']}"]
            self._exec(nxt, spec)

    def _set(self, t, **kw):
        with self.lock:
            t.update(kw)

    def _exec(self, t, spec):
        if not pu.has_key(self.project):
            self._set(t, status="failed", message="未配置 API Key，无法生成。请在配置阶段填写 Key。")
            return
        cmd = build_gen_cmd(self.project, t["category"], spec)
        if not cmd:
            self._set(t, status="failed", message=f"未知分类：{t['category']}")
            return
        buf = []
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
            for line in proc.stdout:
                buf.append(line)
                upd = {}
                m = PCT.search(line)
                if m:
                    upd["progress"] = max(0, min(100, int(m.group(1))))
                ln = line.strip()
                if ln:
                    upd["message"] = ln[:140]   # 实时状态行：前端在卡片上显示"正在做什么"
                if upd:
                    self._set(t, **upd)
            proc.wait()
        except Exception as e:
            self._set(t, status="failed", message=f"启动生成失败：{e}")
            return
        if proc.returncode == 0:
            self._set(t, status="done", progress=100, message="")
        else:
            tail = "".join(buf).strip()[-1200:]
            self._set(t, status="failed", message=tail or "生成失败")

    def snapshot(self):
        with self.lock:
            pub = []
            for t in self.tasks:
                d = {k: t[k] for k in ("task_id", "category", "item_id", "label",
                                       "status", "progress", "message", "cost")}
                d["spec"] = self.specs.get(f"{t['category']}::{t['item_id']}", {})
                pub.append(d)
        totals = {s: sum(1 for x in pub if x["status"] == s)
                  for s in ("queued", "running", "done", "failed", "canceled")}
        totals["total"] = len(pub)
        return {"tasks": pub, "totals": totals,
                "generating": totals["queued"] + totals["running"] > 0,
                "cost_total": round(sum(x["cost"] for x in pub), 2)}


class ReviewState:
    """状态读写 + 各分类条目规范化。"""

    def __init__(self, project):
        self.project = project

    def load(self):
        return pu.load_state(self.project)

    def save(self, state):
        pu.save_state(self.project, state)

    def _char_item(self, c):
        tv = c.get("three_view") or {}
        media = [{"type": "image", "src": _media_url(p), "name": os.path.basename(p), "caption": v}
                 for v, p in tv.items() if p]
        if not media and c.get("image"):
            media = [{"type": "image", "src": _media_url(c["image"]), "name": os.path.basename(c["image"]), "caption": ""}]
        voice = c.get("voice") or {}
        if voice.get("sample"):
            media.append({"type": "audio", "src": _media_url(voice["sample"]),
                          "name": os.path.basename(voice["sample"]), "caption": "配音"})
        return {"id": c["id"], "title": c.get("name") or c["id"],
                "meta": (c.get("gender") or ""), "prompt": c.get("prompt", ""),
                "model": c.get("model", ""), "ratio": c.get("ratio", "16:9"),
                "references": _ref_list(c.get("reference")),
                "media": media, "decision": c.get("review_decision", "通过"),
                "note": c.get("review_note", ""), "status": c.get("status", "draft")}

    def _simple_item(self, it):
        src = it.get("image")
        media = [{"type": "image", "src": _media_url(src), "name": os.path.basename(src) if src else "", "caption": ""}] if src else []
        return {"id": it["id"], "title": it.get("name") or it["id"],
                "meta": it.get("scene_id", ""), "prompt": it.get("prompt", ""),
                "model": it.get("model", ""), "ratio": it.get("ratio", ""),
                "references": _ref_list(it.get("reference")),
                "media": media, "decision": it.get("review_decision", "通过"),
                "note": it.get("review_note", ""), "status": it.get("status", "draft")}

    def _clip_item(self, cl):
        src = cl.get("video_url") or cl.get("local_path")
        media = [{"type": "video", "src": _media_url(src),
                  "name": os.path.basename(src) if src and not src.startswith("http") else (cl["id"] + ".mp4"),
                  "caption": f"{cl.get('kind','')} {cl.get('resolution','')}"}] if src else []
        inp = cl.get("inputs", {})
        return {"id": cl["id"], "title": cl["id"],
                "meta": f"{cl.get('kind','')} · {cl.get('mode','')}",
                "prompt": cl.get("prompt", ""), "model": cl.get("model", ""),
                "resolution": cl.get("resolution", "480p"), "duration": cl.get("duration", 5),
                "ratio": cl.get("ratio", ""),
                "references": _ref_list(inp.get("first_frame"), inp.get("last_frame"), inp.get("reference", [])),
                "media": media, "decision": cl.get("review_decision", "通过"),
                "note": cl.get("review_note", ""), "status": cl.get("status", "draft")}

    def _voice_item(self, c):
        voice = c.get("voice") or {}
        media = []
        if voice.get("sample"):
            media = [{"type": "audio", "src": _media_url(voice["sample"]),
                      "name": os.path.basename(voice["sample"]), "caption": "当前配音"}]
        return {"id": c["id"], "title": c.get("name") or c["id"],
                "meta": ("已配音" if voice.get("sample") else "未配音"),
                "voice_id": voice.get("voice_id", ""), "text": voice.get("sample_text", ""),
                "media": media, "references": [], "prompt": "",
                "decision": c.get("voice_decision", "通过"), "note": c.get("voice_note", ""),
                "status": "done" if voice.get("sample") else "draft"}

    def items(self, state, key):
        if key == "characters":
            return [self._char_item(c) for c in state.get("characters", [])]
        if key == "scenes":
            return [self._simple_item(s) for s in state.get("scenes", [])]
        if key == "shots":
            return [self._simple_item(s) for s in state.get("shots", [])]
        if key == "clips":
            return [self._clip_item(c) for c in state.get("clips", [])]
        if key == "voices":
            return [self._voice_item(c) for c in state.get("characters", [])]
        return []

    def payload(self):
        state = self.load()
        cfg = state.get("config", pu.default_config())
        cats, items = [], {}
        for c in CATEGORIES:
            its = self.items(state, c["key"])
            items[c["key"]] = its
            cats.append({**c, "count": len(its)})
        img_models = [{"id": m, "price": p} for m, p in sa.IMAGE_PRICE.items()]
        vid_models = [m for m in dict.fromkeys([cfg.get("video", {}).get("model"), sa.DEFAULT_VIDEO_MODEL]) if m]
        return {
            "title": state.get("title") or "短剧项目", "phase": state.get("phase", ""),
            "project": self.project, "config": cfg, "categories": cats, "items": items,
            "options": {"image_models": img_models, "video_models": vid_models,
                        "ratios": RATIOS, "resolutions": RESOLUTIONS},
            "has_key": pu.has_key(self.project),
        }


class Handler(BaseHTTPRequestHandler):
    rs = None
    gq = None
    project = None
    server_ref = None

    def log_message(self, *a):
        pass

    def _send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}

    def _safe_path(self, rel):
        full = os.path.abspath(os.path.join(self.project, rel))
        root = os.path.abspath(self.project)
        if os.path.commonpath([full, root]) != root or not os.path.isfile(full):
            return None
        return full

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/state":
            self._send_json(self.rs.payload())
            return
        if parsed.path == "/api/tasks":
            self._send_json(self.gq.snapshot())
            return
        if parsed.path == "/media":
            q = urllib.parse.parse_qs(parsed.query)
            full = self._safe_path((q.get("path") or [""])[0])
            if not full:
                self.send_error(404)
                return
            mime = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            body = self._read_body()
        except Exception as e:
            self._send_json({"ok": False, "error": f"请求体解析失败：{e}"}, 400)
            return

        if parsed.path == "/api/key":
            k = (body.get("key") or "").strip()
            if not k:
                self._send_json({"ok": False, "error": "Key 为空"}, 400)
                return
            kp = pu.key_path(self.project)
            with open(kp, "w", encoding="utf-8") as f:
                f.write(k)
            try:
                os.chmod(kp, 0o600)
            except Exception:
                pass
            os.environ["SENSEAUDIO_KEY_FILE"] = kp  # 让本进程后续生成立即拾取
            self._send_json({"ok": True, "has_key": True})
            return
        if parsed.path == "/api/config":
            state = self.rs.load()
            pu.apply_config(state, body.get("config") or {})
            pu.log(state, "实时更新配置（审核页）")
            self.rs.save(state)
            self._send_json({"ok": True, "config": state["config"]})
            return
        if parsed.path == "/api/decision":
            state = self.rs.load()
            self._apply_decision(state, body.get("category"), body.get("id"),
                                 body.get("decision", "通过"), body.get("note", ""))
            self.rs.save(state)
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/regenerate":
            self._enqueue_edit(body)
            return
        if parsed.path == "/api/retry":
            t = self.gq.retry(body.get("category"), body.get("id"))
            self._send_json({"ok": bool(t), "task": t})
            return
        if parsed.path == "/api/stop":
            self.gq.stop()
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/finish":
            self._finish(body)
            return
        self.send_error(404)

    def _apply_decision(self, state, key, iid, decision, note):
        listname = {"voices": "characters"}.get(key, key)
        it = pu.find(state.get(listname, []), iid)
        if not it:
            return
        if key == "voices":
            it["voice_decision"], it["voice_note"] = decision, note
        else:
            it["review_decision"], it["review_note"] = decision, note
            it["status"] = "approved" if decision == "通过" else "draft"

    def _enqueue_edit(self, body):
        """用户在卡片上改了之后点「重新生成」：合并原始 spec + 本次编辑字段，入队。"""
        key, iid = body.get("category"), body.get("id")
        refs = list(body.get("references") or [])
        for i, uri in enumerate(body.get("references_add") or []):
            rel = save_datauri(self.project, f"{iid}_ref_{i}", uri)
            if rel:
                refs.append(rel)
        base = dict(self.gq.specs.get(f"{key}::{iid}", {}))
        base.update({"category": key, "id": iid, "references": refs})
        for f in EDITABLE:
            if f in body and body[f] not in (None, ""):
                base[f] = body[f]
        if "sample" in body:
            base["sample"] = bool(body["sample"])
        t = self.gq.enqueue(base)
        self._send_json({"ok": True, "task": t})

    def _finish(self, body):
        action = body.get("action") or "继续"
        state = self.rs.load()
        result = {"action": action, "phase": state.get("phase", ""),
                  "summary": {c["key"]: [
                      {"id": it["id"], "decision": it.get("decision"), "note": it.get("note"),
                       "status": it.get("status")} for it in self.rs.items(state, c["key"])]
                      for c in CATEGORIES},
                  "tasks": self.gq.snapshot()["tasks"]}
        os.makedirs(pu.subdir(self.project, "review"), exist_ok=True)
        with open(os.path.join(pu.subdir(self.project, "review"), "review_result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        pu.log(state, f"审核页提交：{action}")
        self.rs.save(state)
        self._send_json({"ok": True, "action": action})
        if self.server_ref:
            threading.Thread(target=self.server_ref.shutdown, daemon=True).start()


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>确认 · 实时审核</title>
<style>
:root{--bg:#0c0e13;--panel:#141823;--panel2:#10131c;--card:#1b2029;--card2:#161a23;--ink:#eef1f6;--mut:#99a1b2;--soft:#727b90;
--ok:#34d399;--no:#fb7185;--line:#262c39;--line2:#343c4b;--accent:#8aa4ff;--accent2:#a98bff;--ring:rgba(138,164,255,.40)}
@media(prefers-color-scheme:light){:root{--bg:#f3f5fb;--panel:#fff;--panel2:#f7f9fd;--card:#fff;--card2:#f5f8fd;--ink:#171b24;--mut:#5a6376;--soft:#8089a0;--line:#e7ebf4;--line2:#dde3ef;--ring:rgba(74,108,247,.30)}}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Segoe UI,sans-serif;-webkit-font-smoothing:antialiased;
background:radial-gradient(900px 460px at 100% -8%,rgba(138,164,255,.13),transparent 60%),radial-gradient(740px 420px at -6% 2%,rgba(169,139,255,.10),transparent 55%),var(--bg)}
::selection{background:rgba(138,164,255,.32)}
.app{display:flex;height:100vh;overflow:hidden}
aside{width:230px;flex:none;background:linear-gradient(180deg,var(--panel),var(--panel2));border-right:1px solid var(--line);display:flex;flex-direction:column;padding:18px 14px}
.brand{display:flex;align-items:center;gap:11px;padding:2px 8px 18px;font-weight:700;font-size:15.5px;letter-spacing:.01em}
.brand i{width:9px;height:24px;border-radius:6px;background:linear-gradient(180deg,var(--accent),var(--accent2));display:inline-block;box-shadow:0 4px 12px rgba(138,164,255,.45);flex:none}
.brand span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
nav{display:flex;flex-direction:column;gap:4px}
.nav-i{position:relative;display:flex;align-items:center;gap:11px;padding:10px 12px;border-radius:12px;color:var(--mut);font-size:14px;cursor:pointer;transition:.15s;user-select:none}
.nav-i:hover{color:var(--ink);background:var(--card2)}
.nav-i.active{color:var(--ink);background:color-mix(in srgb,var(--accent) 15%,transparent);font-weight:600}
.nav-i.active::before{content:"";position:absolute;left:-3px;top:50%;transform:translateY(-50%);width:3px;height:18px;border-radius:3px;background:linear-gradient(180deg,var(--accent),var(--accent2))}
.nav-i .ico{font-size:17px;width:20px;text-align:center}
.nav-i .cnt{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:11.5px;color:var(--soft);background:var(--bg);border:1px solid var(--line);border-radius:999px;padding:1px 8px;min-width:24px;justify-content:center}
.nav-i.active .cnt{color:var(--ink)}
.nav-i .dot{width:7px;height:7px;border-radius:50%;background:var(--accent);animation:pulse 1.1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.side-foot{margin-top:auto;display:flex;flex-direction:column;gap:8px;padding-top:12px}
.side-btn{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:12px;color:var(--mut);font-size:13.5px;cursor:pointer;border:1px solid var(--line);background:var(--card2);text-decoration:none;transition:.15s}
.side-btn:hover{color:var(--ink);border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}.side-btn .ico{font-size:16px}
main{flex:1;min-width:0;display:flex;flex-direction:column}
.top{padding:16px 26px 0;background:color-mix(in srgb,var(--panel) 80%,transparent);backdrop-filter:saturate(150%) blur(10px);-webkit-backdrop-filter:saturate(150%) blur(10px);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:6}
.top-row{display:flex;align-items:center;gap:12px;padding-bottom:14px}
.top h1{font-size:19px;margin:0;font-weight:700;letter-spacing:.01em}.top .sub{color:var(--mut);font-size:12.5px;flex:1}
.pbar{display:flex;align-items:center;gap:12px;padding:0 0 14px}
.pbar.hide{display:none}
.pbar .ptext{font-size:12px;color:var(--mut);white-space:nowrap}
.track{flex:1;height:7px;background:var(--card2);border:1px solid var(--line);border-radius:99px;overflow:hidden}
.track>span{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));width:0;transition:width .3s;border-radius:99px}
.scroll{flex:1;overflow:auto;padding:22px 26px 36px}
.scroll::-webkit-scrollbar{width:11px}.scroll::-webkit-scrollbar-thumb{background:var(--line2);border-radius:99px;border:3px solid transparent;background-clip:padding-box}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:18px;max-width:1280px}
.card{background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--line);border-radius:18px;padding:16px 17px;box-shadow:0 10px 30px rgba(0,0,0,.20);transition:.18s}
.card:hover{transform:translateY(-2px);border-color:var(--line2)}
.card.running{border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
.card.queued{opacity:.7;border-style:dashed}
.card.failed{border-color:var(--no)}
.card.rev{border-color:var(--no)}
.ch{display:flex;align-items:center;gap:9px;margin-bottom:12px}
.ch h3{font-size:16px;margin:0 auto 0 0;font-weight:650}
.badge{font-size:11px;padding:3px 10px;border-radius:999px;font-weight:600;letter-spacing:.02em}
.badge.done{color:#06281c;background:var(--ok)}.badge.running{color:#0a1230;background:var(--accent)}
.badge.queued{color:var(--mut);background:var(--card2);border:1px solid var(--line2)}
.badge.failed{color:#3a0f16;background:var(--no)}
.pill{font-size:11.5px;color:var(--mut);background:var(--card2);border:1px solid var(--line);padding:3px 10px;border-radius:999px}
.cstat{margin-bottom:11px}
.cprog{display:flex;align-items:center;gap:8px}.cprog .track{height:7px}.cprog .pp{font-size:11px;color:var(--mut);min-width:34px;text-align:right}
.cmsg{font-size:11.5px;color:var(--soft);margin-top:7px;line-height:1.5;word-break:break-all;max-height:46px;overflow:auto;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.skeleton{height:158px;border-radius:13px;border:1px solid var(--line);background:repeating-linear-gradient(135deg,#1d2230,#1d2230 14px,#232a3a 14px,#232a3a 28px);display:flex;align-items:center;justify-content:center;color:var(--mut);font-size:12px}
@media(prefers-color-scheme:light){.skeleton{background:repeating-linear-gradient(135deg,#eef1f8,#eef1f8 14px,#e5eaf4 14px,#e5eaf4 28px)}}
.errbox{border:1px solid var(--no);background:color-mix(in srgb,var(--no) 12%,transparent);color:var(--no);border-radius:12px;padding:10px 12px;font-size:12.5px;max-height:100px;overflow:auto;white-space:pre-wrap}
.media{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px;margin-bottom:11px}
.thumb{position:relative;border-radius:13px;overflow:hidden;background:#000;border:1px solid var(--line);flex:0 0 auto}
.thumb img,.thumb video{height:176px;width:auto;max-width:266px;display:block;object-fit:cover;cursor:zoom-in;transition:.25s}
.thumb:hover img{transform:scale(1.04)}
.thumb .dl{position:absolute;top:8px;right:8px;width:30px;height:30px;border-radius:9px;background:rgba(8,10,16,.6);color:#fff;text-align:center;line-height:32px;text-decoration:none;border:1px solid rgba(255,255,255,.18);opacity:0;transition:.15s;backdrop-filter:blur(4px)}
.thumb:hover .dl{opacity:1}.thumb .dl:hover{background:var(--accent);color:#0a1230}
.cap{font-size:11px;color:var(--mut);text-align:center;margin-top:5px}
.aud{display:flex;flex-direction:column;gap:5px;align-items:flex-start}.aud audio{width:248px}
.lbl{font-size:12px;color:var(--mut);margin:11px 0 5px;font-weight:500}
textarea,input[type=text],input[type=number],select{width:100%;background:var(--bg);border:1px solid var(--line2);color:var(--ink);border-radius:10px;padding:9px 11px;font:13px/1.5 inherit;transition:.12s}
textarea{resize:vertical;min-height:62px}
textarea:focus,input:focus,select:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
.refs{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
.ref{position:relative;width:66px;height:66px;border-radius:11px;overflow:hidden;border:1px solid var(--line2);transition:.15s}.ref:hover{border-color:var(--accent)}
.ref img{width:100%;height:100%;object-fit:cover;cursor:zoom-in}.ref.removed{opacity:.32;filter:grayscale(1)}
.ref .rx{position:absolute;top:2px;right:2px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,.62);color:#fff;font-size:11px;line-height:20px;border:0;cursor:pointer;text-align:center;transition:.12s}.ref .rx:hover{background:var(--no)}
.ref-up{width:66px;height:66px;border-radius:11px;border:1px dashed var(--line2);color:var(--mut);font-size:12px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:.15s}.ref-up:hover{color:var(--accent);border-color:var(--accent)}
.setbox{background:color-mix(in srgb,var(--bg) 50%,transparent);border:1px solid var(--line);border-radius:13px;padding:12px 13px;margin:13px 0}
.setbox .sgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.setbox label{font-size:12px;color:var(--mut);display:block}
.foot{display:flex;align-items:center;gap:10px;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:13px;margin-top:6px}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:11px;overflow:hidden}
.seg button{background:var(--bg);color:var(--mut);border:0;font-size:13px;padding:8px 14px;cursor:pointer;transition:.12s}
.seg button+button{border-left:1px solid var(--line2)}
.seg button.on.ok{background:var(--ok);color:#06281c;font-weight:600}.seg button.on.no{background:var(--no);color:#3a0f16;font-weight:600}
.btn{background:linear-gradient(180deg,var(--accent),var(--accent2));color:#0a1230;border:0;border-radius:12px;padding:10px 16px;font-weight:650;font-size:13.5px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;box-shadow:0 4px 14px rgba(138,164,255,.30);transition:.15s}
.btn:hover{filter:brightness(1.05);transform:translateY(-1px)}.btn:active{transform:translateY(0)}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line2);box-shadow:none}.btn.ghost:hover{border-color:var(--accent)}
.btn[disabled]{opacity:.4;cursor:not-allowed;filter:none;transform:none;box-shadow:none}
.btn.sm{padding:7px 12px;font-size:12.5px}.btn.regen{margin-left:auto}.note{flex:1;min-width:140px}
.empty{min-height:54vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:var(--mut);gap:7px;padding:40px}
.empty .ico{width:74px;height:74px;border-radius:22px;display:flex;align-items:center;justify-content:center;font-size:33px;background:color-mix(in srgb,var(--accent) 14%,transparent);border:1px solid var(--line2);margin-bottom:10px}
.empty h3{margin:0;color:var(--ink);font-size:16.5px;font-weight:650}
.empty p{margin:0;font-size:13.5px;max-width:380px;line-height:1.7}
.empty a{color:var(--accent);text-decoration:none;font-weight:600;cursor:pointer}.empty a:hover{text-decoration:underline}
.toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(8px);background:var(--card);border:1px solid var(--line2);color:var(--ink);padding:11px 17px;border-radius:12px;font-size:13px;box-shadow:0 12px 34px rgba(0,0,0,.34);opacity:0;transition:.2s;pointer-events:none;z-index:80;max-width:80vw}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.scrim{position:fixed;inset:0;background:rgba(6,8,12,.6);backdrop-filter:blur(3px);display:none;z-index:40}.scrim.show{display:block}
.drawer{position:fixed;top:0;right:0;bottom:0;width:392px;max-width:90vw;background:linear-gradient(180deg,var(--panel),var(--panel2));border-left:1px solid var(--line2);transform:translateX(100%);transition:.24s cubic-bezier(.2,.8,.2,1);z-index:50;display:flex;flex-direction:column;box-shadow:-20px 0 60px rgba(0,0,0,.3)}
.drawer.show{transform:none}.drawer h2{font-size:15px;margin:0;font-weight:650}
.dh{display:flex;align-items:center;padding:18px 20px;border-bottom:1px solid var(--line)}.dh .x{margin-left:auto;background:transparent;border:0;color:var(--mut);font-size:18px;cursor:pointer;border-radius:8px;width:30px;height:30px}.dh .x:hover{background:var(--card2);color:var(--ink)}
.dbody{padding:18px 20px;overflow:auto}.dbody .grp{margin-bottom:20px}.dbody .grp>.t{font-size:11.5px;color:var(--accent);font-weight:600;letter-spacing:.05em;text-transform:uppercase;margin-bottom:10px}
.dfield{margin-bottom:11px}.dfield label{font-size:12px;color:var(--mut);display:block;margin-bottom:5px}
.chk{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink)}.chk input{width:auto}
.savehint{font-size:12px;color:var(--mut);padding:0 20px 16px}
#lb{position:fixed;inset:0;z-index:90;background:rgba(6,8,12,.88);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;padding:32px}
#lb.show{display:flex}#lb img{max-width:92vw;max-height:82vh;border-radius:14px;box-shadow:0 24px 70px rgba(0,0,0,.6)}
#lb .bar{position:absolute;top:18px;right:18px;display:flex;gap:10px}
#lb .bar a,#lb .bar button{background:rgba(255,255,255,.13);color:#fff;border:1px solid rgba(255,255,255,.22);border-radius:11px;padding:9px 15px;font-size:14px;text-decoration:none;cursor:pointer;font-weight:600}#lb .bar a:hover,#lb .bar button:hover{background:rgba(255,255,255,.24)}
</style></head>
<body>
<div class="app">
  <aside>
    <div class="brand"><i></i><span id="brand">短剧项目</span></div>
    <nav id="nav"></nav>
    <div class="side-foot">
      <a class="side-btn" id="wdlink" href="#" target="_blank"><span class="ico">📂</span>打开工作目录</a>
      <div class="side-btn" onclick="openSettings()"><span class="ico">⚙</span>设置（配置）</div>
    </div>
  </aside>
  <main>
    <div class="top">
      <div class="top-row">
        <h1 id="cat-title">…</h1><span class="sub" id="cat-sub"></span>
        <button class="btn" id="btn-go" onclick="finish('继续')">继续</button>
        <button class="btn ghost" onclick="finish('重做这一批')">重做这一批</button>
      </div>
      <div class="pbar hide" id="pbar">
        <span class="ptext" id="ptext"></span>
        <span class="track"><span id="pfill"></span></span>
        <span class="ptext" id="pcost"></span>
        <button class="btn ghost sm" onclick="stopAll()">全部停止</button>
      </div>
    </div>
    <div class="scroll"><div class="cards" id="cards"></div></div>
  </main>
</div>

<div class="scrim" id="scrim" onclick="closeSettings()"></div>
<div class="drawer" id="drawer">
  <div class="dh"><h2>⚙ 配置（随时可改，即时生效）</h2><button class="x" onclick="closeSettings()">✕</button></div>
  <div class="dbody" id="dbody"></div>
  <div class="savehint">改动会自动保存并应用到后续生成。</div>
</div>
<div id="lb" onclick="if(event.target.id==='lb')this.classList.remove('show')">
  <div class="bar"><a id="lbdl" href="#" download>⬇ 下载</a><button onclick="document.getElementById('lb').classList.remove('show')">✕</button></div>
  <img id="lbimg" src="" alt="">
</div>
<div class="toast" id="toast"></div>

<script>
let S=null, CUR=null, TASK={}, TOTS=null;
const $=s=>document.querySelector(s);
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('show');clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('show'),2600);}
function zoom(src,name){$('#lbimg').src=src;const d=$('#lbdl');d.href=src;d.download=name||'image';$('#lb').classList.add('show');}
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});return r.json();}
function tkey(cat,id){return cat+'::'+id;}

async function load(){S=await api('/api/state');
  $('#brand').textContent=S.title;
  $('#wdlink').href=S.project?('file://'+S.project):'#';
  renderSettings();
  const first=S.categories.find(c=>c.count>0)||S.categories[0];
  CUR=first.key; renderNav(); renderCards();
  applyHash();
  poll();
}
function applyHash(){const h=(location.hash||'').slice(1);
  if(h==='config'){openSettings();return;}
  if(h&&S.categories.some(c=>c.key===h))select(h);}
window.addEventListener('hashchange',applyHash);
function catTasks(key){return Object.values(TASK).filter(t=>t.category===key&&(t.status==='running'||t.status==='queued'));}
function renderNav(){const ICON={user:'🧑',photo:'🏙️',clapperboard:'🎬',movie:'🎞️',microphone:'🎙️'};
  $('#nav').innerHTML=S.categories.map(c=>{const act=catTasks(c.key).length;
    return `<div class="nav-i${c.key===CUR?' active':''}" onclick="select('${c.key}')"><span class="ico">${ICON[c.icon]||'•'}</span>${c.label}<span class="cnt">${act?'<span class=dot></span>':''}${c.count}</span></div>`;}).join('');}
function select(key){CUR=key;const cat=S.categories.find(c=>c.key===key);
  $('#cat-title').textContent=cat.label;$('#cat-sub').textContent=`${cat.count} 项`;
  renderNav();renderCards();
  try{history.replaceState(null,'','#'+key);}catch(e){}}

function mediaHTML(m){if(!m.src)return '';
  if(m.type==='video')return `<div class="thumb"><video controls preload="metadata" src="${m.src}"></video><a class="dl" href="${m.src}" download="${m.name}">⬇</a></div>`;
  if(m.type==='audio')return `<div class="aud"><audio controls src="${m.src}"></audio><a class="dl" style="position:static;width:auto;height:auto;line-height:1.4;padding:3px 9px;font-size:12px" href="${m.src}" download="${m.name}">⬇ 下载</a></div>`;
  return `<div class="thumb"><img src="${m.src}" loading="lazy" onclick="zoom('${m.src}','${m.name}')"><a class="dl" href="${m.src}" download="${m.name}" onclick="event.stopPropagation()">⬇</a></div>`;}
function opt(list,val){return list.map(o=>{const v=typeof o==='string'?o:o.id;const lab=typeof o==='string'?o:`${o.id}（~${o.price}元/张）`;return `<option value="${v}"${v===val?' selected':''}>${lab}</option>`;}).join('');}
function setBox(it){const o=S.options;
  if(CUR==='clips')return `<div class="setbox"><div class="lbl" style="margin-top:0">🎛 本片生成设置（覆盖全局）</div><div class="sgrid">
    <label>模型<select data-f="model">${opt(o.video_models,it.model||S.config.video.model)}</select></label>
    <label>分辨率<select data-f="resolution">${opt(o.resolutions,it.resolution)}</select></label>
    <label>画幅<select data-f="ratio">${opt(o.ratios,it.ratio||S.config.ratio)}</select></label>
    <label>时长(秒)<input type="number" data-f="duration" min="4" max="15" value="${it.duration||5}"></label>
  </div><label class="chk" style="margin-top:9px"><input type="checkbox" data-f="sample"> 用样片(更省积分)重生成</label></div>`;
  if(CUR==='voices')return `<div class="setbox"><div class="lbl" style="margin-top:0">🎛 配音设置</div><div class="sgrid">
    <label>音色 ID<input type="text" data-f="voice_id" value="${it.voice_id||''}" placeholder="如 female_0033_b"></label><label>　</label></div>
    <div class="lbl">台词文本</div><textarea data-f="text" placeholder="要合成的台词">${it.text||''}</textarea></div>`;
  return `<div class="setbox"><div class="lbl" style="margin-top:0">🎛 本图生成设置（覆盖全局）</div><div class="sgrid">
    <label>模型<select data-f="model">${opt(o.image_models,it.model||S.config.image.model_final)}</select></label>
    <label>画幅<select data-f="ratio">${opt(o.ratios,it.ratio||S.config.ratio)}</select></label>
  </div><label class="chk" style="margin-top:9px"><input type="checkbox" data-f="sample"> 用样片模型(更省)重生成</label></div>`;}

function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function statHTML(t){if(!t)return '';
  if(t.status==='queued')return `<div class="cstat"><div class="cmsg">⏳ 排队中，等待空闲生成位…</div></div>`;
  if(t.status==='running')return `<div class="cstat"><div class="cprog"><span class="track"><span style="display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));width:${t.progress==null?30:t.progress}%;transition:width .3s"></span></span><span class="pp">${t.progress==null?'生成中':t.progress+'%'}</span></div>${t.message?`<div class="cmsg">${esc(t.message)}</div>`:''}</div>`;
  if(t.status==='failed')return `<div class="cstat"><div class="errbox">${esc(t.message||'生成失败')}</div></div>`;
  return '';}

function cardHTML(it){const t=TASK[tkey(CUR,it.id)];
  const st=t?t.status:(it.media&&it.media.length?'done':'idle');
  const cls=st==='running'?'running':st==='queued'?'queued':st==='failed'?'failed':(it.decision==='需修改'?'rev':'');
  const badge={done:'<span class="badge done">✓ 完成</span>',running:'<span class="badge running">⟳ 生成中</span>',
    queued:'<span class="badge queued">排队中</span>',failed:'<span class="badge failed">✕ 失败</span>'}[st]||'';
  const isVoice=CUR==='voices';
  let mediaArea;
  if(st==='running'||st==='queued') mediaArea=`<div class="skeleton">${st==='queued'?'等待前序任务…':'渲染中…'}</div>`;
  else{const m=(it.media||[]).map(x=>`<div>${mediaHTML(x)}${x.caption?`<div class="cap">${x.caption}</div>`:''}</div>`).join('');
    mediaArea=m?`<div class="media">${m}</div>`:'<div class="skeleton">（暂无产出）</div>';}
  const refs=(it.references||[]).map(r=>`<div class="ref" data-path="${r}" data-removed="0"><img src="/media?path=${encodeURIComponent(r)}" onclick="zoom('/media?path=${encodeURIComponent(r)}','ref')"><button class="rx" onclick="toggleRef(this)">✕</button></div>`).join('');
  const editBlock=isVoice?'':`<div class="lbl">生图提示词（可改）</div><textarea data-f="prompt">${it.prompt||''}</textarea>
    <div class="lbl">参考图（可删 / 上传）</div><div class="refs">${refs}<label class="ref-up">＋ 上传<input type="file" accept="image/*" multiple hidden onchange="addRefs(this)"></label></div>`;
  const okOn=it.decision!=='需修改';
  const busy=(st==='running'||st==='queued');
  const action=st==='failed'?`<button class="btn regen" onclick="regen(this)">↻ 重试</button>`
    :`<button class="btn regen" onclick="regen(this)"${busy?' disabled':''}>↻ ${isVoice?'重新配音':'重新生成这一张'}</button>`;
  return `<div class="card ${cls}" data-id="${it.id}">
    <div class="ch"><h3>${it.title}</h3>${it.meta?`<span class="pill">${it.meta}</span>`:''}${badge}</div>
    ${statHTML(t)}
    ${mediaArea}
    ${editBlock}
    ${setBox(it)}
    <div class="foot">
      <div class="seg"><button class="ok${okOn?' on':''}" onclick="decide(this,'通过')">✓ 通过</button><button class="no${!okOn?' on':''}" onclick="decide(this,'需修改')">✎ 需修改</button></div>
      <input class="note" type="text" data-f="note" placeholder="意见（可留空）" value="${(it.note||'').replace(/"/g,'&quot;')}">
      ${action}
    </div></div>`;}

function taskItem(t){const s=t.spec||{};   // 把"还没落进 state 的在途任务"合成为占位卡片
  return {id:t.item_id,title:t.label||t.item_id,meta:'',prompt:s.prompt||'',
    model:s.model||'',ratio:s.ratio||'',resolution:s.resolution||'480p',duration:s.duration||5,
    references:s.references||[],voice_id:s.voice_id||'',text:s.text||'',
    media:[],decision:'通过',note:''};}
function renderCards(){const items=(S.items[CUR]||[]).slice();
  const ids=new Set(items.map(it=>it.id));
  // 首次生成的资产在完成前不在 state 里——把它们的任务也渲染成占位卡片，实时显示状态
  Object.values(TASK).forEach(t=>{ if(t.category===CUR && !ids.has(t.item_id)){ items.push(taskItem(t)); ids.add(t.item_id); }});
  if(items.length){$('#cards').innerHTML=items.map(cardHTML).join('');return;}
  const cat=S.categories.find(c=>c.key===CUR)||{};
  const ico={characters:'🧑',scenes:'🏙️',shots:'🎬',clips:'🎞️',voices:'🎙️'}[CUR]||'✨';
  const hint=S.has_key
    ? '还没有内容。在对话里告诉我你想要的角色 / 场景 / 分镜，我会开始生成——进度会实时显示在这里。'
    : '还没有内容。先打开 <a onclick="openSettings()">设置 · 填 API Key</a>，填好我就开始生成。';
  $('#cards').innerHTML=`<div class="empty"><div class="ico">${ico}</div><h3>${cat.label||''}</h3><p>${hint}</p></div>`;}

function toggleRef(b){const d=b.parentElement;const r=d.dataset.removed==='1'?'0':'1';d.dataset.removed=r;d.classList.toggle('removed',r==='1');}
const PENDING={};
function addRefs(input){const id=input.closest('.card').dataset.id;PENDING[id]=PENDING[id]||[];
  [...input.files].forEach(f=>{const rd=new FileReader();rd.onload=()=>{PENDING[id].push(rd.result);
    const d=document.createElement('div');d.className='ref';d.dataset.added='1';d.innerHTML=`<img src="${rd.result}">`;
    input.closest('.refs').insertBefore(d,input.closest('.ref-up'));};rd.readAsDataURL(f);});input.value='';}
function decide(btn,val){const seg=btn.parentElement;seg.querySelectorAll('button').forEach(b=>b.classList.remove('on'));btn.classList.add('on');
  const card=btn.closest('.card');card.classList.toggle('rev',val==='需修改');
  api('/api/decision',{category:CUR,id:card.dataset.id,decision:val,note:card.querySelector('[data-f=note]').value});}
function cardFields(card){const o={};card.querySelectorAll('[data-f]').forEach(e=>{o[e.dataset.f]=e.type==='checkbox'?e.checked:e.value;});
  o.references=[...card.querySelectorAll('.ref')].filter(d=>d.dataset.added!=='1'&&d.dataset.removed!=='1').map(d=>d.dataset.path);
  o.references_add=PENDING[card.dataset.id]||[];return o;}
async function regen(btn){const card=btn.closest('.card');const id=card.dataset.id;const f=cardFields(card);
  const res=await api('/api/regenerate',Object.assign({category:CUR,id},f));
  if(!res.ok){toast('入队失败');return;}
  PENDING[id]=[];toast('已加入生成队列：'+id);poll();}

async function poll(){let r;try{r=await api('/api/tasks');}catch(e){setTimeout(poll,2000);return;}
  const prev=TASK;TASK={};r.tasks.forEach(t=>TASK[tkey(t.category,t.item_id)]=t);TOTS=r.totals;
  updateTop(r);renderNav();
  // 当前分类的状态签名：覆盖 state 已有项 + 在途任务（含进度/状态行），任何变化都重画
  const sig=r.tasks.filter(t=>t.category===CUR).map(t=>t.item_id+':'+t.status+':'+(t.progress||'')+':'+(t.message||'')).join('|')
    +'#'+(S.items[CUR]||[]).map(it=>it.id).join(',');
  const changed=sig!==poll._last;poll._last=sig;
  const justFinished=r.tasks.some(t=>{const p=prev[tkey(t.category,t.item_id)];return p&&p.status!==t.status&&(t.status==='done'||t.status==='failed');});
  if(justFinished){S=await api('/api/state');}
  if(changed||justFinished)renderCards();
  if(r.generating)setTimeout(poll,1200);
}
function updateTop(r){const t=r.totals,pb=$('#pbar'),go=$('#btn-go');
  if(r.generating){pb.classList.remove('hide');
    $('#ptext').textContent=`⏳ 生成中 · ${t.done} 完成 / ${t.running} 进行 / ${t.queued} 排队${t.failed?' / '+t.failed+' 失败':''}`;
    $('#pfill').style.width=(t.total?Math.round(t.done/t.total*100):0)+'%';
    $('#pcost').textContent='~'+r.cost_total+' 元';
    go.disabled=true;go.title='等生成完再继续';}
  else{pb.classList.add('hide');go.disabled=false;go.title='';
    if(t.failed){$('#cat-sub').textContent=`有 ${t.failed} 项生成失败，可在卡片上「重试」`;}}
}
async function stopAll(){await api('/api/stop',{});toast('已请求停止：排队任务取消，当前任务跑完即停');poll();}
async function finish(action){if($('#btn-go').disabled&&action==='继续')return;
  if(action==='重做这一批'&&!confirm('整批重做？'))return;
  await api('/api/finish',{action});
  document.body.innerHTML='<div style="height:100vh;display:flex;align-items:center;justify-content:center;color:var(--mut);font-size:15px;text-align:center;padding:40px">已提交「'+action+'」。可以关闭本页，回到对话即可，助手会继续。</div>';}

function openSettings(){$('#scrim').classList.add('show');$('#drawer').classList.add('show');try{history.replaceState(null,'','#config');}catch(e){}}
function closeSettings(){$('#scrim').classList.remove('show');$('#drawer').classList.remove('show');try{history.replaceState(null,'','#'+(CUR||''));}catch(e){}}
async function saveKey(){const el=$('#apikey');const k=(el.value||'').trim();if(!k){toast('请粘贴 API Key');return;}
  const r=await api('/api/key',{key:k});
  if(r.ok){S=await api('/api/state');renderSettings();renderNav();renderCards();toast('API Key 已保存，可以开始生成了');}
  else toast('保存失败：'+(r.error||''));}
function renderSettings(){const c=S.config,o=S.options;const sel=(f,list,val)=>`<select data-c="${f}">${opt(list,val)}</select>`;
  const keyState=S.has_key?'<span style="color:var(--ok)">· 已配置</span>':'<span style="color:var(--no)">· 未配置，下面填入</span>';
  const access=`<div class="grp" id="grp-access"><div class="t">接入与目录</div>
     <div class="dfield"><label>工作目录（固定根目录）</label>
       <div style="display:flex;gap:8px;align-items:center"><input type="text" value="${S.project||''}" readonly style="flex:1">
       <a class="btn ghost sm" href="file://${S.project||''}" target="_blank">打开</a></div></div>
     <div class="dfield"><label>API Key ${keyState}</label>
       <div style="display:flex;gap:8px"><input type="password" id="apikey" placeholder="sk-…（粘贴后点保存，只写入 .sa_key）" style="flex:1">
       <button class="btn sm" onclick="saveKey()">保存</button></div></div></div>`;
  $('#dbody').innerHTML=access+`
   <div class="grp"><div class="t">全局</div>
     <div class="dfield"><label>画幅</label>${sel('ratio',o.ratios,c.ratio)}</div>
     <div class="dfield"><label>视觉风格</label><input type="text" data-c="style" value="${c.style||''}" placeholder="如 写实电影感"></div></div>
   <div class="grp"><div class="t">图像</div>
     <div class="dfield"><label>成片模型</label>${sel('image.model_final',o.image_models,c.image.model_final)}</div>
     <div class="dfield"><label>样片模型</label>${sel('image.model_sample',o.image_models,c.image.model_sample)}</div></div>
   <div class="grp"><div class="t">视频</div>
     <div class="dfield"><label>视频模型</label>${sel('video.model',o.video_models,c.video.model)}</div>
     <div class="dfield"><label>样片分辨率</label>${sel('video.resolution_sample',o.resolutions,c.video.resolution_sample)}</div>
     <div class="dfield"><label>成片分辨率</label>${sel('video.resolution_final',o.resolutions,c.video.resolution_final)}</div>
     <div class="dfield"><label>默认时长(秒)</label><input type="number" data-c="video.duration_default" min="4" max="15" value="${c.video.duration_default}"></div>
     <div class="dfield"><label class="chk"><input type="checkbox" data-c="video.generate_audio" ${c.video.generate_audio?'checked':''}> 生成音轨</label></div>
     <div class="dfield"><label class="chk"><input type="checkbox" data-c="video.watermark" ${c.video.watermark?'checked':''}> 水印</label></div></div>
   <div class="grp"><div class="t">语音</div>
     <div class="dfield"><label>默认音色 ID</label><input type="text" data-c="audio.voice_id" value="${c.audio.voice_id||''}" placeholder="如 female_0033_b"></div>
     <div class="dfield"><label>语速</label><input type="number" data-c="audio.speed" step="0.1" min="0.5" max="2" value="${c.audio.speed}"></div></div>`;
  $('#dbody').querySelectorAll('[data-c]').forEach(e=>e.addEventListener('change',saveSettings));}
function setDeep(o,path,val){const ks=path.split('.');let cur=o;for(let i=0;i<ks.length-1;i++){cur[ks[i]]=cur[ks[i]]||{};cur=cur[ks[i]];}cur[ks[ks.length-1]]=val;}
async function saveSettings(){const cfg={};
  $('#dbody').querySelectorAll('[data-c]').forEach(e=>{let v;if(e.type==='checkbox')v=e.checked;else if(e.type==='number')v=parseFloat(e.value)||0;else v=e.value;setDeep(cfg,e.dataset.c,v);});
  const res=await api('/api/config',{config:cfg});if(res.ok){S.config=res.config;toast('配置已更新');}}

load();
</script>
</body></html>"""


def daemonize(logpath):
    """双重 fork + setsid：脱离父会话/进程组，使服务在启动命令返回或被回收后仍存活（Unix）。

    必须在创建任何线程/绑定端口之前调用——fork 只保留当前线程。
    """
    if os.fork() > 0:
        os._exit(0)            # 原始进程立即退出 → 启动命令瞬间返回
    os.setsid()
    if os.fork() > 0:
        os._exit(0)            # 第一子进程退出，孙进程在新会话里独立存活
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
    ap.add_argument("--plan", default=None, help="生成计划 JSON：启动即入队，边开页面边生成")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--concurrency", type=int, default=4, help="并行生成的任务数（默认 4）")
    ap.add_argument("--daemon", action="store_true",
                    help="脱离会话后台常驻（推荐）：不随启动命令返回/回合结束被回收")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    project = os.path.abspath(args.project)
    pu.load_state(project)   # fork 前校验项目存在，错误能直接反馈给启动命令
    review_dir = pu.subdir(project, "review")
    os.makedirs(review_dir, exist_ok=True)
    url_file = os.path.join(review_dir, "serve_url.txt")
    try:
        os.remove(url_file)  # 清掉上一次的 URL，避免读到旧端口
    except OSError:
        pass

    # 守护化：必须在建线程/绑定端口之前（之后的一切都在独立存活的守护进程里）
    if args.daemon and os.name == "posix":
        daemonize(os.path.join(review_dir, "serve.log"))

    pu.use_project_key(project)
    Handler.rs = ReviewState(project)
    Handler.gq = GenQueue(project, concurrency=args.concurrency)
    Handler.project = project

    # 载入生成计划：先入队，下面服务一启动 worker 即开始并行生成
    if args.plan and os.path.exists(args.plan):
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
        for spec in plan.get("tasks", []):
            if spec.get("category") and spec.get("id"):
                Handler.gq.enqueue(spec)

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
    with open(os.path.join(review_dir, "serve.pid"), "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    if not args.no_open:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    print(f"SERVE:{url}")
    print(f"LINK:[打开实时审核页 ↗]({url})")
    print(f"实时审核服务已启动：{url}（并发 {args.concurrency} 路边生成边看进度；用户点「继续/重做这一批」后本服务自动退出）")
    print(f"  深链：{url}#config（配置/Key）、{url}#characters、{url}#scenes、{url}#shots、{url}#clips、{url}#voices", flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

    result_path = os.path.join(pu.subdir(project, "review"), "review_result.json")
    if os.path.exists(result_path):
        print("RESULT:" + result_path)
        print(open(result_path, encoding="utf-8").read())


if __name__ == "__main__":
    main()
