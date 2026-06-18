"""项目状态读写工具。state.json 是各轮对话之间的唯一事实来源。"""
import json
import os
import uuid
from datetime import datetime, timezone


# ---------- 固定的工作目录结构（单一事实来源） ----------
# 用户只需决定「根目录」(work_dir)；其下的所有相对路径都由这里固定，无需用户选择。
# 各生成脚本与实时应用都从这里取目录名，保证落盘位置一致、可预期。
SUBDIRS = [
    ("characters", "assets/characters", "人设图", "🧑"),   # 角色三视图 / 设定图
    ("scenes",     "assets/scenes",     "场景图", "🏙️"),   # 场景概念图
    ("shots",      "assets/shots",      "分镜图", "🎬"),   # 分镜 / 机位预览
    ("voices",     "assets/voices",     "语音参考", "🎙️"),  # 配音 / 声音素材
    ("refs",       "assets/refs",       "参考素材", "🖼️"),  # 用户上传 / 抽帧的参考图
    ("output",     "output",            "成片输出", "🎞️"),  # 生成的视频
    ("review",     "review",            "审核页", "📝"),    # 实时应用产物（serve_url.txt / plan.json / review_result.json）
    ("docs",       "docs",              "文稿", "📄"),      # 剧本 / 说明
]


def subdir(project, key):
    """取某类资产的固定子目录绝对路径。key 见 SUBDIRS 第一列。"""
    rel = next((r for k, r, *_ in SUBDIRS if k == key), key)
    return os.path.join(project, rel)


def ensure_dirs(project):
    """按固定结构创建/补齐所有子目录。"""
    for _, rel, *_ in SUBDIRS:
        os.makedirs(os.path.join(project, rel), exist_ok=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def default_config():
    """全局生成配置。用户在实时应用「设置」面板里修改（/api/config → apply_config）。"""
    return {
        "ratio": "9:16",
        "style": "",
        "image": {
            "model_final": "senseaudio-image-2.0-260319",
            "model_sample": "senseaudio-image-1.0-260319",
            "use_async": False,
        },
        "video": {
            "model": "doubao-seedance-2-0-260128",
            "resolution_sample": "480p",
            "resolution_final": "1080p",
            "duration_default": 5,
            "generate_audio": True,
            "watermark": True,
        },
        "audio": {
            "tts_model": "senseaudio-tts-1.5-260319",
            "voice_id": "",
            "format": "mp3",
            "speed": 1.0,
        },
    }


def deep_merge(base, override):
    """把 override 深合并进 base（就地修改 base）。"""
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def apply_config(state, cfg):
    """把提交的配置合并进 state['config']。忽略 api_key 等敏感字段。"""
    cfg = dict(cfg or {})
    for k in ("api_key", "work_dir", "_note"):
        cfg.pop(k, None)
    state.setdefault("config", default_config())
    deep_merge(state["config"], cfg)
    return state["config"]


def default_state(title=""):
    return {
        "project_id": str(uuid.uuid4()),
        "title": title,
        "created_at": now_iso(),
        "phase": "align",  # align | mode | generate
        "config": default_config(),
        "story": {"logline": "", "summary": "", "beats": []},
        "characters": [],   # 见 templates/state-schema.md
        "scenes": [],
        "shots": [],        # 分镜/机位
        "clips": [],        # 已生成或待生成的视频片段
        "history": [],      # 操作日志
    }


def state_path(project):
    return os.path.join(project, "state.json")


def key_path(project):
    return os.path.join(project, ".sa_key")


def use_project_key(project):
    """若环境未提供 SENSEAUDIO_API_KEY，但项目里有 .sa_key，则指向它。

    生成脚本在调用 API 前调用本函数，使 sa_client 能读到密钥文件。
    """
    if not os.environ.get("SENSEAUDIO_API_KEY"):
        kp = key_path(project)
        if os.path.exists(kp):
            os.environ["SENSEAUDIO_KEY_FILE"] = kp


def has_key(project=None):
    """工作区是否已有可用的 API Key（环境变量或项目 .sa_key）。"""
    if os.environ.get("SENSEAUDIO_API_KEY"):
        return True
    kf = os.environ.get("SENSEAUDIO_KEY_FILE")
    if kf and os.path.exists(kf):
        return True
    return bool(project and os.path.exists(key_path(project)))


NO_KEY_MSG = (
    "❌ 未配置 SenseAudio API Key，无法真实生成。\n"
    "【不要用 --mock 顶替，也不要产出 mock 成品。】\n"
    "正确做法：把用户引导到实时应用的配置区（serve_review.py 的 …/#config），在那里填入 API Key（保存即写 .sa_key、即时生效），再重试本次生成。"
)


def require_key(project):
    """真实生成前的硬性检查：无 Key 则打印指引并以非 0 退出（绝不退化成 mock）。"""
    use_project_key(project)
    if not has_key(project):
        print(NO_KEY_MSG)
        raise SystemExit(2)


def load_state(project):
    path = state_path(project)
    if not os.path.exists(path):
        raise FileNotFoundError(f"未找到 {path}，请先运行 init_project.py")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(project, state):
    state["updated_at"] = now_iso()
    with open(state_path(project), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def log(state, message):
    state.setdefault("history", []).append({"at": now_iso(), "message": message})


def find(items, item_id):
    for it in items:
        if it.get("id") == item_id:
            return it
    return None


# ---------- 角色一致性（防止性别/服装/身份漂移） ----------

def character_anchor(state, char_ids):
    """把出场角色的"身份锚点"拼成一段强约束前缀，注入到分镜/视频 prompt。

    这是防止"男生变女生 / 衣服对不上 / 角色消失"的关键：每次生成都重申角色身份。
    """
    parts = []
    for cid in char_ids or []:
        c = find(state.get("characters", []), cid)
        if not c:
            continue
        g = f"，{c['gender']}" if c.get("gender") else ""
        desc = c.get("prompt") or c.get("description") or ""
        parts.append(f"{c.get('name') or cid}（{cid}{g}）：{desc}")
    if not parts:
        return ""
    return ("【严格保持以下角色一致：性别、发型、瞳色、服装、五官特征必须与设定完全一致，"
            "不得增减或替换角色】" + "；".join(parts) + "。")


def character_image(state, cid):
    c = find(state.get("characters", []), cid)
    if not c:
        return None
    tv = c.get("three_view") or {}
    return tv.get("front") or tv.get("sheet") or c.get("image")


def scene_image(state, sid):
    s = find(state.get("scenes", []), sid)
    return s.get("image") if s else None


def upsert(items, item_id, **fields):
    it = find(items, item_id)
    if it is None:
        it = {"id": item_id}
        items.append(it)
    it.update(fields)
    return it
