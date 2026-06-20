"""生成任务队列 + worker 线程池。"""
import os
import subprocess
import threading

import sa_client as sa
import project_utils as pu
import ensure_env as env

from review.common import (
    PCT, MAX_RETRIES, STAGE_OF, build_export_cmd, est_cost, export_fail_message,
)


class GenQueue:
    def __init__(self, project, concurrency=4):
        self.project = project
        self.concurrency = max(1, int(concurrency))
        self.lock = threading.Lock()
        self.tasks = []
        self.specs = {}
        self.seq = 0
        self._stop = False
        self._procs = {}
        self.workers = []

    def _key(self, spec):
        return f"{spec['category']}::{spec['id']}"

    def active_item_keys(self):
        with self.lock:
            return {f"{t['category']}::{t['item_id']}" for t in self.tasks
                    if t["status"] in ("queued", "running")}

    def _prepare_spec(self, spec, resolve_refs=False):
        spec = pu.normalize_plan_task(dict(spec))
        if resolve_refs:
            try:
                st = pu.load_state(self.project)
                pu.resolve_generation_refs(st, spec.get("category"), spec)
            except FileNotFoundError:
                pass
        return spec

    def enqueue(self, spec, start=True, resolve_refs=False):
        spec = self._prepare_spec(spec, resolve_refs=resolve_refs)
        with self.lock:
            k = self._key(spec)
            self.specs[k] = spec
            self.seq += 1
            t = {"task_id": self.seq, "category": spec["category"], "item_id": spec["id"],
                 "label": spec.get("name") or spec["id"], "status": "queued" if start else "draft",
                 "progress": None, "message": "", "cost": est_cost(spec["category"], spec)}
            self.tasks = [x for x in self.tasks
                          if not (x["category"] == spec["category"] and x["item_id"] == spec["id"]
                                  and x["status"] != "running")]
            self.tasks.append(t)
        if start:
            self._stop = False
            self._ensure_workers()
        return t

    def start_drafts(self, scope):
        n = 0
        with self.lock:
            for t in self.tasks:
                if t["status"] != "draft":
                    continue
                if (scope.get("all")
                        or (scope.get("id") and t["item_id"] == scope.get("id")
                            and t["category"] == scope.get("category"))
                        or (scope.get("category") and not scope.get("id")
                            and t["category"] == scope["category"])
                        or (scope.get("categories") and t["category"] in scope["categories"])):
                    t["status"] = "queued"
                    n += 1
        if n:
            self._stop = False
            self._ensure_workers()
        return n

    def generate_clips(self, sample):
        """一键生成尚未完成样片/成片的 clip。"""
        by_id = {}
        with self.lock:
            for s in self.specs.values():
                if s.get("category") == "clips":
                    by_id[s["id"]] = dict(s)
        try:
            st = pu.load_state(self.project)
        except Exception:
            st = {}
        for cl in st.get("clips", []):
            if cl["id"] not in by_id:
                inp = cl.get("inputs", {})
                by_id[cl["id"]] = {
                    "category": "clips", "id": cl["id"], "prompt": cl.get("prompt", ""),
                    "characters": ",".join(cl.get("characters") or []),
                    "shots": ",".join(cl.get("shot_ids") or []),
                    "ratio": cl.get("ratio", ""),
                    "references": inp.get("reference") or [],
                    "duration": (cl.get("sample") or cl.get("final") or {}).get("duration"),
                    "model": cl.get("model", ""),
                }
        n = 0
        clip_by_id = {c["id"]: c for c in st.get("clips", [])}
        for iid, sp in by_id.items():
            cl = clip_by_id.get(iid, {})
            if pu.clip_part_done(cl, sample):
                continue
            sp = dict(sp)
            sp["sample"] = bool(sample)
            self.enqueue(sp, start=True)
            n += 1
        return n

    def stop(self, category=None, item_id=None):
        procs_to_kill = []
        with self.lock:
            targets = []
            for t in self.tasks:
                if t["status"] not in ("queued", "running"):
                    continue
                if category and item_id:
                    if t["category"] == category and t["item_id"] == item_id:
                        targets.append(t)
                else:
                    targets.append(t)
            if not category:
                self._stop = True
            for t in targets:
                t["status"] = "canceled"
                t["message"] = "已停止"
                k = f"{t['category']}::{t['item_id']}"
                p = self._procs.get(k)
                if p:
                    procs_to_kill.append(p)
        for p in procs_to_kill:
            try:
                p.terminate()
            except Exception:
                pass
        return len(targets)

    def _ensure_workers(self):
        with self.lock:
            self.workers = [w for w in self.workers if w.is_alive()]
            if self._stop:
                return
            queued = sum(1 for t in self.tasks if t["status"] == "queued")
            need = min(self.concurrency - len(self.workers), queued)
        for _ in range(max(0, need)):
            w = threading.Thread(target=self._run, daemon=True)
            with self.lock:
                self.workers.append(w)
            w.start()

    def _pick_locked(self):
        queued = [t for t in self.tasks if t["status"] == "queued"]
        if not queued:
            return None
        for stg in sorted({STAGE_OF.get(t["category"], 1) for t in queued}):
            earlier_busy = any(STAGE_OF.get(t["category"], 1) < stg and t["status"] in ("queued", "running")
                               for t in self.tasks)
            if earlier_busy:
                continue
            t = next((t for t in queued if STAGE_OF.get(t["category"], 1) == stg), None)
            if t:
                return t
        return None

    def _run(self):
        while True:
            with self.lock:
                if self._stop:
                    break
                nxt = self._pick_locked()
                if not nxt:
                    break
                nxt["status"] = "running"
                nxt["progress"] = None
                spec = self.specs[f"{nxt['category']}::{nxt['item_id']}"]
            self._exec(nxt, spec)
            self._ensure_workers()

    def _set(self, t, **kw):
        with self.lock:
            t.update(kw)

    @staticmethod
    def _retryable_fail(msg):
        if not msg:
            return True
        low = msg.lower()
        for s in (
            "版权", "copyright", "未配置 API Key", "未找到 API Key",
            "未知分类", "导出环境未就绪", "找不到参考文件",
        ):
            if s in msg or s.lower() in low:
                return False
        return True

    def _on_gen_log(self, t, line):
        upd = {}
        m = PCT.search(line)
        if m:
            upd["progress"] = max(0, min(100, int(m.group(1))))
        ln = line.strip()
        if ln:
            upd["message"] = ln[:140]
        if upd:
            self._set(t, **upd)

    def _run_gen(self, t, spec):
        cat = t["category"]
        with self.lock:
            if t["status"] == "canceled":
                return False, "", True
        try:
            if cat in ("characters", "scenes", "shots"):
                import gen_image as gi
                typ = {"characters": "character", "scenes": "scene", "shots": "shot"}[cat]
                refs = spec.get("references") or []
                gi.run_image_generation(
                    self.project, img_type=typ, item_id=spec["id"],
                    prompt=spec.get("prompt") or "", name=spec.get("name") or "",
                    reference=",".join(refs) if refs else None,
                    style_ref=spec.get("style_ref"), gender=spec.get("gender"),
                    build=spec.get("build"), scene=spec.get("scene"),
                    characters=spec.get("characters"), views=spec.get("views"),
                    ratio=spec.get("ratio"), model=spec.get("model"),
                    on_log=lambda line: self._on_gen_log(t, line),
                )
            elif cat == "clips":
                import gen_video as gv
                refs = spec.get("references") or []

                def on_progress(pct, line):
                    self._set(t, progress=max(0, min(100, int(pct))), message=line.strip()[:140])

                gv.run_video_generation(
                    self.project, item_id=spec["id"], prompt=spec.get("prompt") or "",
                    reference=",".join(refs) if refs else None,
                    characters=spec.get("characters"), shots=spec.get("shots"),
                    duration=spec.get("duration"), ratio=spec.get("ratio"),
                    model=spec.get("model"), resolution=spec.get("resolution"),
                    sample=bool(spec.get("sample")), prev_video=spec.get("prev_video"),
                    next_video=spec.get("next_video"), audio=spec.get("audio"),
                    on_log=lambda line: self._on_gen_log(t, line),
                    on_progress=on_progress,
                )
            elif cat == "exports":
                return self._run_export_subprocess(t, spec)
            else:
                return False, f"未知分类：{cat}", False
            with self.lock:
                if t["status"] == "canceled":
                    return False, "", True
            return True, "", False
        except sa.APIError as e:
            return False, str(e), False
        except Exception as e:
            return False, f"生成失败：{e}", False

    def _run_export_subprocess(self, t, spec):
        cmd = build_export_cmd(self.project, spec)
        buf = []
        tk = f"{t['category']}::{t['item_id']}"
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
            with self.lock:
                self._procs[tk] = proc
            for line in proc.stdout:
                with self.lock:
                    if t["status"] == "canceled":
                        proc.terminate()
                        break
                buf.append(line)
                self._on_gen_log(t, line)
            proc.wait()
        except Exception as e:
            return False, f"启动导出失败：{e}", False
        finally:
            with self.lock:
                self._procs.pop(tk, None)
        with self.lock:
            if t["status"] == "canceled":
                return False, "", True
        if proc.returncode == 0:
            return True, "", False
        tail = "".join(buf).strip()[-1200:]
        return False, export_fail_message(tail) or "导出失败", False

    def _exec(self, t, spec):
        if not pu.has_key(self.project):
            self._set(t, status="failed", message="未配置 API Key，无法生成。请在配置阶段填写 Key。")
            return
        if t["category"] == "exports" and not env.has_ffmpeg():
            ok, _, msgs = env.ensure(["ffmpeg"], install=True)
            if not ok:
                self._set(t, status="failed",
                          message="导出环境未就绪（缺 ffmpeg）：\n" + "\n".join(msgs))
                return
        spec = self._prepare_spec(spec)
        last_msg = "生成失败"
        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                self._set(t, status="running", progress=None,
                          message=f"第 {attempt}/{MAX_RETRIES} 次重试…")
            ok, msg, canceled = self._run_gen(t, spec)
            if canceled:
                return
            if ok:
                self._set(t, status="done", progress=100, message="")
                return
            last_msg = msg
            if attempt >= MAX_RETRIES or not self._retryable_fail(msg):
                break
        fail_msg = last_msg
        if attempt > 0 and self._retryable_fail(last_msg):
            fail_msg = f"{last_msg}\n（已自动重试 {min(attempt, MAX_RETRIES)} 次，仍失败）"
        self._set(t, status="failed", message=fail_msg)

    def snapshot(self):
        with self.lock:
            pub = []
            for t in self.tasks:
                d = {k: t[k] for k in ("task_id", "category", "item_id", "label",
                                       "status", "progress", "message", "cost")}
                d["spec"] = self.specs.get(f"{t['category']}::{t['item_id']}", {})
                pub.append(d)
        totals = {s: sum(1 for x in pub if x["status"] == s)
                  for s in ("queued", "running", "done", "failed", "canceled", "draft")}
        totals["total"] = len(pub)
        return {"tasks": pub, "totals": totals,
                "generating": totals["queued"] + totals["running"] > 0,
                "cost_total": round(sum(x["cost"] or 0 for x in pub), 2)}

    def ingest_plan(self, body, rs):
        """备 plan 草稿；跳过已通过/已有产出/队列中的项。返回 {prepared, skipped, skipped_ids}。"""
        force = bool(body.get("force"))
        if body.get("story"):
            state = rs.load()
            pu.apply_plan_meta(state, body)
            rs.save(state)
        try:
            state = rs.load()
        except Exception:
            state = {}
        active = self.active_item_keys()
        prepared, skipped_ids = 0, []
        for spec in (body.get("tasks") or []):
            if not spec.get("category") or not spec.get("id"):
                continue
            skip, reason = pu.plan_task_skippable(state, spec, active, force=force)
            if skip:
                skipped_ids.append({"id": spec["id"], "category": spec["category"], "reason": reason})
                continue
            self.enqueue(spec, start=False, resolve_refs=True)
            prepared += 1
        return {"prepared": prepared, "skipped": len(skipped_ids), "skipped_ids": skipped_ids}
