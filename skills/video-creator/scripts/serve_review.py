"""本地实时审核 + 生成进度服务：左侧分类侧边栏 + 右侧卡片，**先开前端，再边生成边看进度**。

本服务是整套 skill 的**唯一前端**，**活的**：
- 助手只**准备**任务（plan.json / POST /api/plan，落为「待生成」草稿）并打开网页；**生成由用户在 UI 点「开始生成」触发**。
  生成后用后台 worker 池**并行**跑（默认 4 路），每个资产是占位卡片，带状态（待生成/排队/生成中%/完成/失败）+ 顶部总进度。
- 生成分阶段、队列按阶段门控：阶段1 人设+场景 → 阶段2 分镜（用人设/场景图作参考）→ 阶段3 视频 → 阶段4 导出。
- 用户在页面上看进度；完成的卡片可立刻改提示词/参考图/模型/设置并「重新生成」；失败/超时会**自动重试最多 3 次**，仍失败可在卡片上手动「重试」；
  点侧边栏「设置」随时改全局配置/Key、即时落盘生效。
- 服务**常驻**（无「继续/重做」提交闭环）。助手续作下一阶段时：读 /api/state 判断阶段 → POST /api/plan 推进。
  停止：用户点侧边栏「关闭服务」、助手 `--stop`、或 kill serve.pid。

接口：
  GET  /                 单页应用（侧边栏[按三阶段分组] + 卡片 + 进度 + 设置面板）
  GET  /api/state        全量状态：分类、各分类条目、阶段、配置、可选模型/画幅/分辨率
  GET  /api/tasks        生成任务队列与进度（**前端轮询**；助手勿轮询等待完成，用 status.py 读盘）
  GET  /api/files        列出工作目录内可选的参考图（供卡片「📁 目录」选图）
  GET  /media?path=rel   流式返回项目内的图片/音频/视频（带防越权校验）
  POST /api/config       深合并配置并落盘（实时生效）
  POST /api/key          保存 API Key 到 .sa_key
  POST /api/decision     保存某条目的「通过/需修改」+ 意见
  POST /api/references   保存参考图列表（粘贴/上传/选图后立即落盘，切页不丢）
  POST /api/regenerate   按本条目编辑后的提示词/参考图/模型/设置重新生成（**仅用户在 UI 点「重试/重新生成」**）
  POST /api/plan         把一批新任务备为「待生成」草稿（**助手唯一可用的推进接口**）
  POST /api/generate     把「待生成」草稿转入队列开始生成（**仅用户在 UI 点「开始生成」**；助手禁止调用）
  POST /api/generate-clips  一键生成所有 clip 样片/成片（**仅用户在 UI 触发**；助手禁止调用）
  POST /api/stop         停止：取消所有排队任务（当前任务跑完即停）
  POST /api/shutdown     关停本地服务

  python serve_review.py --project ./drama [--plan plan.json] [--port 8765] [--daemon] [--stop]
  （常驻启动加 --daemon：脚本自行双 fork 脱离会话，启动命令瞬间返回、服务独立存活，见 SKILL.md 启动协议）

plan.json 形如：{"tasks":[
  {"category":"characters","id":"char_01","name":"林夏","prompt":"...","gender":"女"},
  {"category":"scenes","id":"scene_01","name":"便利店","prompt":"..."},
  {"category":"shots","id":"shot_01","prompt":"...","characters":"char_01","scene":"scene_01"},
  {"category":"clips","id":"clip_01","prompt":"...","shots":"shot_01","characters":"char_01","duration":5},
  {"category":"exports","id":"export_01","title":"成片","order":"clip_01,clip_02"}
]}
  （clips 不用写 sample/分辨率——出样片还是成片由用户在「样片生成/成片生成」子页触发时决定）
"""
import argparse
import json
import mimetypes
import os
import signal
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sa_client as sa
import project_utils as pu
import ensure_env as env

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
PCT = re.compile(r"(\d{1,3})%")
MAX_RETRIES = 3  # 失败/超时后自动重试次数（不含首次）

CATEGORIES = [{"key": c["key"], "label": c["label"], "icon": c["icon"], "kind": c["kind"]}
              for c in pu.PIPELINE_CATEGORIES]
STAGE_OF = pu.STAGE_OF
STAGES = pu.STAGES
RATIOS = pu.RATIOS
RESOLUTIONS = pu.RESOLUTIONS
# 用户在卡片上可直接改、并覆盖原始计划参数的字段
EDITABLE = ("prompt", "model", "ratio", "resolution", "duration", "sample")


def _media_url(rel):
    if not rel:
        return None
    if rel.startswith(("http://", "https://")):
        return rel
    return "/media?path=" + urllib.parse.quote(rel)


def _load_index_html():
    path = os.path.join(SKILL_ROOT, "templates", "review.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _refs(spec_or_item):
    """读取 references 列表（兼容 state 里遗留的 reference 单数字段）。"""
    refs = spec_or_item.get("references")
    if refs:
        return list(refs)
    r = spec_or_item.get("reference")
    if not r:
        return []
    return [r] if isinstance(r, str) else list(r)


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
        if key == "characters":
            if spec.get("gender"):
                cmd += ["--gender", spec["gender"]]
            if spec.get("build"):
                cmd += ["--build", spec["build"]]
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
            cmd += ["--reference", ",".join(refs) if key == "shots" else refs[0]]
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
        shots = spec.get("shots")
        if shots:
            cmd += ["--shots", shots if isinstance(shots, str) else ",".join(shots)]
        if spec.get("prev_video"):
            cmd += ["--prev-video", spec["prev_video"]]
        if spec.get("next_video"):
            cmd += ["--next-video", spec["next_video"]]
        if spec.get("audio"):
            cmd += ["--audio", spec["audio"]]
        if refs:
            cmd += ["--reference", ",".join(refs)]
        return cmd
    if key == "exports":
        order = spec.get("order")
        order = order if isinstance(order, str) else ",".join(order or [])
        cmd = [py, os.path.join(HERE, "concat_clips.py"), "--project", project,
               "--id", iid, "--ids", order]
        if spec.get("title"):
            cmd += ["--title", spec["title"]]
        if spec.get("ratio"):
            cmd += ["--ratio", spec["ratio"]]
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
        self._procs = {}         # task_key -> 运行中的 subprocess
        self.workers = []        # 并行 worker 线程池

    def _key(self, spec):
        return f"{spec['category']}::{spec['id']}"

    def _prepare_spec(self, spec):
        """规范化 plan 字段并补全参考图。"""
        spec = pu.normalize_plan_task(dict(spec))
        try:
            st = pu.load_state(self.project)
            pu.resolve_generation_refs(st, spec.get("category"), spec)
        except FileNotFoundError:
            pass
        return spec

    def enqueue(self, spec, start=True):
        """加入任务。start=True 立即排队生成；start=False 仅作为「待生成」草稿。"""
        spec = self._prepare_spec(spec)
        with self.lock:
            k = self._key(spec)
            self.specs[k] = spec
            self.seq += 1
            t = {"task_id": self.seq, "category": spec["category"], "item_id": spec["id"],
                 "label": spec.get("name") or spec["id"], "status": "queued" if start else "draft",
                 "progress": None, "message": "", "cost": est_cost(spec["category"], spec)}
            # 同一资产的非运行中旧任务移除（重推/重生成时刷新），避免堆叠
            self.tasks = [x for x in self.tasks
                          if not (x["category"] == spec["category"] and x["item_id"] == spec["id"]
                                  and x["status"] != "running")]
            self.tasks.append(t)
        if start:
            self._stop = False   # 用户显式启动生成，清除之前的「全部停止」标记
            self._ensure_workers()
        return t

    def start_drafts(self, scope):
        """把「待生成」草稿转入队列开始生成。scope: {all} / {category} / {categories:[...]} / {category,id}。"""
        n = 0
        with self.lock:
            for t in self.tasks:
                if t["status"] != "draft":
                    continue
                if (scope.get("all")
                        or (scope.get("id") and t["item_id"] == scope.get("id") and t["category"] == scope.get("category"))
                        or (scope.get("category") and not scope.get("id") and t["category"] == scope["category"])
                        or (scope.get("categories") and t["category"] in scope["categories"])):
                    t["status"] = "queued"
                    n += 1
        if n:
            self._stop = False
            self._ensure_workers()
        return n

    def generate_clips(self, sample):
        """一键生成所有 clip 的样片(sample=True)或成片(sample=False)：沿用各 clip 的 spec、覆盖 sample 标记后入队。

        内存里有 spec 就用内存的；服务重启后内存为空，则从 state.clips 兜底重建 spec。
        """
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
                by_id[cl["id"]] = {"category": "clips", "id": cl["id"], "prompt": cl.get("prompt", ""),
                                   "characters": ",".join(cl.get("characters") or []),
                                   "shots": ",".join(cl.get("shot_ids") or []),
                                   "ratio": cl.get("ratio", ""), "references": inp.get("reference") or []}
        for sp in by_id.values():
            sp["sample"] = bool(sample)
            self.enqueue(sp, start=True)
        return len(by_id)

    def stop(self, category=None, item_id=None):
        """停止生成：无 scope 时停全部（含 running）；有 category+id 时只停单项。"""
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
        """按并发上限补足 worker（多个 worker 并行从队列取任务）。

        need = 还能再开的 worker 数 = min(并发上限 - 现有 worker, 已排队数)。
        关键：用「并发上限 - 现有 worker」而非「min(并发, 已排队) - worker」，
        否则任务陆续到达（先到的已转 running、不再计入 queued）时池子永远爬不到并发上限。
        """
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
        """阶段门控取下一个 queued 任务：上一阶段还有 queued/running 时，不放行下一阶段。"""
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
            self._ensure_workers()   # 阶段门控可能此刻放开，补足 worker 跑下一阶段

    def _set(self, t, **kw):
        with self.lock:
            t.update(kw)

    @staticmethod
    def _friendly_fail(tail):
        """从子进程 stderr/stdout 尾部提取 APIError，并转成可读说明。"""
        if not tail:
            return ""
        for line in reversed(tail.splitlines()):
            line = line.strip()
            if not line.startswith("sa_client.APIError:"):
                continue
            msg = line.split("sa_client.APIError:", 1)[-1].strip()
            low = msg.lower()
            if "copyright" in low or "版权" in msg or "版权策略" in msg:
                return msg
            return msg
        if "copyright" in tail.lower() or "版权" in tail:
            return sa.format_video_error(
                tail.split("error_message")[-1] if "error_message" in tail else tail[-400:]
            )
        return tail

    @staticmethod
    def _retryable_fail(msg):
        """不可恢复的错误不重试（版权、配置、缺文件等）。"""
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
        """执行生成：图像/视频直接调用核心函数，导出仍走子进程。返回 (成功, 失败说明, 是否用户取消)。"""
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
        """导出拼接仍走子进程（ffmpeg）。"""
        cmd = build_gen_cmd(self.project, t["category"], spec)
        if not cmd:
            return False, f"未知分类：{t['category']}", False
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
            return False, f"启动生成失败：{e}", False
        finally:
            with self.lock:
                self._procs.pop(tk, None)
        with self.lock:
            if t["status"] == "canceled":
                return False, "", True
        if proc.returncode == 0:
            return True, "", False
        tail = "".join(buf).strip()[-1200:]
        return False, self._friendly_fail(tail) or "生成失败", False

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
        return {"id": c["id"], "title": c.get("name") or c["id"],
                "meta": (c.get("gender") or ""), "prompt": c.get("prompt", ""),
                "model": c.get("model", ""), "ratio": c.get("ratio", "16:9"),
                "references": _refs(c),
                "media": media, "decision": c.get("review_decision", "通过"),
                "note": c.get("review_note", ""), "status": c.get("status", "draft")}

    def _simple_item(self, it):
        src = it.get("image")
        media = [{"type": "image", "src": _media_url(src), "name": os.path.basename(src) if src else "", "caption": ""}] if src else []
        return {"id": it["id"], "title": it.get("name") or it["id"],
                "meta": it.get("scene_id", ""), "prompt": it.get("prompt", ""),
                "model": it.get("model", ""), "ratio": it.get("ratio", ""),
                "references": _refs(it),
                "media": media, "decision": it.get("review_decision", "通过"),
                "note": it.get("review_note", ""), "status": it.get("status", "draft")}

    def _clip_item(self, cl):
        def part(kind):
            p = cl.get(kind) or {}
            src = p.get("video_url") or p.get("local_path")
            media = [{"type": "video", "src": _media_url(src),
                      "name": os.path.basename(src) if src and not src.startswith("http") else f"{cl['id']}_{kind}.mp4",
                      "caption": f"{kind} {p.get('resolution', '')}"}] if src else []
            return {"media": media, "status": p.get("status", "draft"),
                    "resolution": p.get("resolution", ""), "duration": p.get("duration", "")}
        inp = cl.get("inputs", {})
        dur = (cl.get("final") or cl.get("sample") or {}).get("duration", 5)
        return {"id": cl["id"], "title": cl["id"], "meta": cl.get("mode", ""),
                "prompt": cl.get("prompt", ""), "model": cl.get("model", ""),
                "duration": dur, "ratio": cl.get("ratio", ""),
                "references": list(inp.get("reference") or []),
                "sample": part("sample"), "final": part("final"),
                "decision": cl.get("review_decision", "通过"),
                "note": cl.get("review_note", ""), "status": cl.get("status", "draft")}

    def _export_item(self, e):
        src = e.get("local_path") or e.get("video_url")
        media = [{"type": "video", "src": _media_url(src),
                  "name": os.path.basename(src) if src and not src.startswith("http") else (e["id"] + ".mp4"),
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
            return [self._simple_item(s) for s in state.get("scenes", [])]
        if key == "shots":
            return [self._simple_item(s) for s in state.get("shots", [])]
        if key == "clips":
            return [self._clip_item(c) for c in state.get("clips", [])]
        if key == "exports":
            return [self._export_item(e) for e in state.get("exports", [])]
        return []

    def payload(self):
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
            body = _load_index_html().encode("utf-8")
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
            # 列出工作目录下的图片（供「从工作目录选参考图」用——浏览器无法把上传框默认目录设到项目里）
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
                    groups.append({"label": label, "files": [os.path.join(rel, f).replace("\\", "/") for f in files]})
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
            # 打包下载全部素材：中间图像 + 视频片段 + 成片导出（assets/ + output/）
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
        """把 assets/（图像/参考）与 output/（视频片段+成片）打成一个 zip，返回字节。"""
        import io
        import zipfile
        buf = io.BytesIO()
        roots = ["assets", "output"]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root in roots:
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
            # AI 只「准备」任务（draft），不自动生成；用户在 UI 点「开始生成」才真正跑。
            if body.get("story"):
                state = self.rs.load()
                pu.apply_plan_meta(state, body)
                self.rs.save(state)
            n = 0
            for spec in (body.get("tasks") or []):
                if spec.get("category") and spec.get("id"):
                    self.gq.enqueue(spec, start=False)
                    n += 1
            self._send_json({"ok": True, "prepared": n})
            return
        if parsed.path == "/api/generate":
            # 用户在 UI 触发生成：把待生成草稿转入队列。scope: {all}/{category}/{categories}/{category,id}
            n = self.gq.start_drafts(body or {"all": True})
            self._send_json({"ok": True, "started": n})
            return
        if parsed.path == "/api/generate-clips":
            # 一键生成所有视频片段的样片(sample=true)或成片(sample=false)
            n = self.gq.generate_clips(bool(body.get("sample")))
            self._send_json({"ok": True, "started": n})
            return
        if parsed.path == "/api/shutdown":
            # 直接关停本地服务（不提交结果）。资产/配置已在工作目录里，安全。
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

    def _persist_item_edit(self, state, key, iid, body, refs):
        """把用户本次编辑写入 state，避免切页后 UI 仍显示旧参考图/提示词。"""
        it = pu.find(state.get(key, []), iid)
        if not it:
            return
        if key == "clips":
            it.setdefault("inputs", {})["reference"] = refs
        else:
            it["references"] = refs
            it.pop("reference", None)
        for f in EDITABLE:
            if f in body and body[f] not in (None, ""):
                it[f] = body[f]

    def _merge_references(self, key, iid, body):
        """合并已有路径与本次粘贴/上传的 data URI，落盘后返回完整 references 列表。"""
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

    def _persist_references(self, key, iid, refs):
        """把 references 写入 state（若已有条目）与内存队列 spec。"""
        state = self.rs.load()
        it = pu.find(state.get(key, []), iid)
        if it:
            if key == "clips":
                it.setdefault("inputs", {})["reference"] = list(refs)
            else:
                it["references"] = list(refs)
                it.pop("reference", None)
            self.rs.save(state)
        k = f"{key}::{iid}"
        with self.gq.lock:
            spec = self.gq.specs.get(k)
            if spec:
                spec["references"] = list(refs)
                if refs:
                    spec.pop("style_ref", None)

    def _save_references(self, body):
        """粘贴/上传/选图后立即保存参考图，避免切页后只显示旧的一张。"""
        key, iid = body.get("category"), body.get("id")
        if not key or not iid:
            self._send_json({"ok": False, "error": "缺少 category/id"}, 400)
            return
        refs = self._merge_references(key, iid, body)
        self._persist_references(key, iid, refs)
        self._send_json({"ok": True, "references": refs})

    def _enqueue_edit(self, body):
        """用户在卡片上改了之后点「重新生成」：合并原始 spec + 本次编辑字段，入队。"""
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
            base.pop("style_ref", None)   # 用户已显式指定参考图，不再回退到画风基准角色图
        state = self.rs.load()
        self._persist_item_edit(state, key, iid, body, refs)
        self.rs.save(state)
        t = self.gq.enqueue(base)
        self._send_json({"ok": True, "task": t, "spec": base})



def daemonize(logpath):
    """双重 fork + setsid：脱离父会话/进程组，使服务在启动命令返回或被回收后仍存活（Unix）。

    必须在创建任何线程/绑定端口之前调用——fork 只保留当前线程。
    重定向 stdin/stdout/stderr，让启动命令的管道立即收到 EOF 而不挂起。
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
    ap.add_argument("--plan", default=None, help="生成计划 JSON：作为「待生成」备好，等用户在 UI 点「开始生成」")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--concurrency", type=int, default=4, help="并行生成的任务数（默认 4）")
    ap.add_argument("--daemon", action="store_true",
                    help="脱离会话后台常驻（推荐）：自行双 fork，不随启动命令返回/回合结束被回收")
    ap.add_argument("--stop", action="store_true",
                    help="停止该项目正在运行的服务（读 review/serve.pid 结束进程）")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    project = os.path.abspath(args.project)
    review_dir = pu.subdir(project, "review")
    os.makedirs(review_dir, exist_ok=True)
    pid_file = os.path.join(review_dir, "serve.pid")
    url_file = os.path.join(review_dir, "serve_url.txt")

    # --stop：结束正在运行的服务
    if args.stop:
        try:
            pid = int(open(pid_file, encoding="utf-8").read().strip())
            os.kill(pid, signal.SIGTERM)
            print(f"已停止服务（PID {pid}）。")
        except (FileNotFoundError, ValueError):
            print("没有正在运行的服务（未找到 serve.pid）。")
        except ProcessLookupError:
            print("服务进程已不存在（可能已关闭）。")
        for f in (pid_file, url_file):
            try:
                os.remove(f)
            except OSError:
                pass
        return

    pu.load_state(project)   # fork 前校验项目存在，错误能直接反馈给启动命令
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

    # 载入生成计划：作为「待生成」草稿备好，等用户在 UI 点「开始生成」才真正跑（AI 只准备、不自动生成）
    if args.plan and os.path.exists(args.plan):
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
        if plan.get("story"):
            state = Handler.rs.load()
            pu.apply_plan_meta(state, plan)
            Handler.rs.save(state)
        for spec in plan.get("tasks", []):
            if spec.get("category") and spec.get("id"):
                Handler.gq.enqueue(spec, start=False)

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
    signal.signal(signal.SIGTERM, _on_term)   # kill / --stop 时干净退出

    if not args.no_open:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    print(f"SERVE:{url}")
    print(f"LINK:[打开实时审核页 ↗]({url})")
    print(f"实时审核服务已启动：{url}（并发 {args.concurrency} 路，按阶段门控；常驻直到用户点「关闭服务」或 --stop）")
    print(f"  深链：{url}#config（配置/Key）、{url}#characters、{url}#scenes、{url}#shots、{url}#clips、{url}#exports", flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        for f in (pid_file, url_file):   # 退出即清理，避免 --stop 命中陈旧 pid
            try:
                os.remove(f)
            except OSError:
                pass


if __name__ == "__main__":
    main()
