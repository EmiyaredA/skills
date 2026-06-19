"""HTTP 请求处理器。"""
import io
import json
import mimetypes
import os
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler

import project_utils as pu

from review.common import EDITABLE, load_index_html


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
            body = load_index_html().encode("utf-8")
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
        if parsed.path == "/api/files":
            exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")
            groups = []
            for key, rel, label, _icon in pu.SUBDIRS:
                if key in ("review", "output", "docs"):
                    continue
                d = os.path.join(self.project, rel)
                if not os.path.isdir(d):
                    continue
                files = sorted(f for f in os.listdir(d) if f.lower().endswith(exts))
                if files:
                    groups.append({"label": label,
                                   "files": [os.path.join(rel, f).replace("\\", "/") for f in files]})
            self._send_json({"groups": groups})
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
        if parsed.path == "/api/export-zip":
            data = self._build_zip()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="drama_export.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def _build_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root in ("assets", "output"):
                base = os.path.join(self.project, root)
                if not os.path.isdir(base):
                    continue
                for dirpath, _dirs, files in os.walk(base):
                    for fn in files:
                        if fn.startswith("."):
                            continue
                        full = os.path.join(dirpath, fn)
                        zf.write(full, os.path.relpath(full, self.project))
        return buf.getvalue()

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
            pu.save_project_key(self.project, k)
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
        if parsed.path == "/api/references":
            self._save_references(body)
            return
        if parsed.path == "/api/stop":
            cat, iid = body.get("category"), body.get("id")
            n = self.gq.stop(cat, iid) if cat and iid else self.gq.stop()
            self._send_json({"ok": True, "stopped": n})
            return
        if parsed.path == "/api/plan":
            result = self.gq.ingest_plan(body, self.rs)
            self._send_json({"ok": True, **result})
            return
        if parsed.path == "/api/generate":
            n = self.gq.start_drafts(body or {"all": True})
            self._send_json({"ok": True, "started": n})
            return
        if parsed.path == "/api/generate-clips":
            n = self.gq.generate_clips(bool(body.get("sample")))
            self._send_json({"ok": True, "started": n})
            return
        if parsed.path == "/api/shutdown":
            self._send_json({"ok": True})
            if self.server_ref:
                threading.Thread(target=self.server_ref.shutdown, daemon=True).start()
            return
        self.send_error(404)

    def _apply_decision(self, state, key, iid, decision, note):
        it = pu.find(state.get(key, []), iid)
        if not it:
            return
        it["review_decision"], it["review_note"] = decision, note
        it["status"] = "approved" if decision == "通过" else "draft"

    def _merge_references(self, key, iid, body):
        refs = list(body.get("references") or [])
        seen = set(refs)
        base_ts = int(time.time() * 1000)
        for i, uri in enumerate(body.get("references_add") or []):
            tag = f"{iid}_ref_{base_ts}_{i}"
            rel = pu.save_data_uri(self.project, tag, uri)
            if rel and rel not in seen:
                refs.append(rel)
                seen.add(rel)
        return refs

    def _persist_refs(self, key, iid, refs):
        """写入 state 与内存队列 spec。"""
        state = self.rs.load()
        it = pu.find(state.get(key, []), iid)
        if it:
            pu.set_refs(it, key, refs)
            self.rs.save(state)
        k = f"{key}::{iid}"
        with self.gq.lock:
            spec = self.gq.specs.get(k)
            if spec:
                spec["references"] = list(refs)
                if refs:
                    spec.pop("style_ref", None)

    def _persist_item_edit(self, state, key, iid, body, refs):
        it = pu.find(state.get(key, []), iid)
        if not it:
            return
        pu.set_refs(it, key, refs)
        for f in EDITABLE:
            if f in body and body[f] not in (None, ""):
                it[f] = body[f]

    def _save_references(self, body):
        key, iid = body.get("category"), body.get("id")
        if not key or not iid:
            self._send_json({"ok": False, "error": "缺少 category/id"}, 400)
            return
        refs = self._merge_references(key, iid, body)
        self._persist_refs(key, iid, refs)
        self._send_json({"ok": True, "references": refs})

    def _enqueue_edit(self, body):
        key, iid = body.get("category"), body.get("id")
        refs = self._merge_references(key, iid, body)
        base = dict(self.gq.specs.get(f"{key}::{iid}", {}))
        base.update({"category": key, "id": iid, "references": refs})
        for f in EDITABLE:
            if f in body and body[f] not in (None, ""):
                base[f] = body[f]
        if "sample" in body:
            base["sample"] = bool(body["sample"])
        if refs:
            base.pop("style_ref", None)
        state = self.rs.load()
        self._persist_item_edit(state, key, iid, body, refs)
        self.rs.save(state)
        t = self.gq.enqueue(base)
        self._send_json({"ok": True, "task": t, "spec": base})
