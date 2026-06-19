"""SenseAudio API 客户端（仅依赖 Python 标准库）。

环境变量：
  SENSEAUDIO_API_KEY    必填。在 https://senseaudio.cn/api-platform/api-key 获取。
  SENSEAUDIO_BASE_URL   可选，默认 https://api.senseaudio.cn

设计要点：
- 本地图片路径会自动转成 data URI 传给 API；http(s)/data URL 原样透传。
- 所有生成脚本共用本模块，--mock 时不发起真实网络请求，写占位文件用于流程自测。
- 切勿把 API Key 写进 state.json 或提交到 git。
"""
import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("SENSEAUDIO_BASE_URL", "https://api.senseaudio.cn").rstrip("/")

# 参考价（官方折扣价，单位：元）。仅用于生成前的成本预估，实际以平台结算为准。
IMAGE_PRICE = {
    "senseaudio-image-2.0-260319": 0.5,   # 高分辨率、效果最佳
    "senseaudio-image-1.0-260319": 0.2,   # 最便宜，适合样片/草稿
    "doubao-seedream-5-0-260128": 0.22,
    "sensenova-u1-fast": 0.5,
}
VIDEO_PRICE_PER_SEC = {"480p": 0.5, "720p": 1.0, "1080p": 3.1}
TTS_PRICE_PER_10K_CHARS = 3.5

# 每个图像模型支持的尺寸（取自官方文档）。索引 0 通常为最小/最省。
IMAGE_SIZES = {
    "senseaudio-image-2.0-260319": {
        "1:1": "1024x1024", "16:9": "1536x864", "9:16": "864x1536",
        "4:3": "1024x1024", "3:4": "864x1536",
    },
    "senseaudio-image-1.0-260319": {
        "1:1": "1328x1328", "16:9": "1664x928", "9:16": "928x1664",
        "4:3": "1584x1056", "3:4": "1056x1584",
    },
    "doubao-seedream-5-0-260128": {
        "1:1": "2048x2048", "16:9": "2304x1728", "9:16": "1728x2304",
    },
    "sensenova-u1-fast": {
        "1:1": "2048x2048", "16:9": "2496x1664", "9:16": "1664x2496",
    },
}

DEFAULT_VIDEO_MODEL = "doubao-seedance-2-0-260128"
DEFAULT_IMAGE_MODEL = "senseaudio-image-2.0-260319"
DEFAULT_TTS_MODEL = "senseaudio-tts-1.5-260319"


class APIError(Exception):
    pass


def _key():
    # 1) 环境变量（SoWork 平台注入时优先）
    k = os.environ.get("SENSEAUDIO_API_KEY")
    if not k:
        # 2) 回退到项目级密钥文件（gitignored，由 save_key.py 写入）
        kf = os.environ.get("SENSEAUDIO_KEY_FILE")
        if kf and os.path.exists(kf):
            k = open(kf, encoding="utf-8").read().strip()
    if not k:
        raise APIError(
            "未找到 API Key。请让用户在配置页填写并提交，助手用 save_key.py 写入项目密钥文件；"
            "或在工作区设置环境变量 SENSEAUDIO_API_KEY。获取：https://senseaudio.cn/api-platform/api-key"
        )
    return k


def _request(method, path, body=None, query=None, timeout=180):
    url = BASE_URL + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_key()}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise APIError(f"HTTP {e.code} {method} {path}: {detail}")
    except urllib.error.URLError as e:
        raise APIError(f"网络错误 {method} {path}: {e}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    # 统一错误检查：部分接口用 code/message 包裹错误。
    if isinstance(payload, dict):
        if payload.get("code") not in (None, 0, "0", 200):
            raise APIError(f"{path} 返回错误: {payload.get('code')} {payload.get('message')}")
        base = payload.get("base_resp")
        if isinstance(base, dict) and base.get("status_code") not in (None, 0):
            raise APIError(f"{path} 返回错误: {base.get('status_msg')}")
    return payload


# ---------- 资源工具 ----------

def to_data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def as_url(ref):
    """本地路径 -> data URI；http(s)/data URL 原样返回；None -> None。"""
    if not ref:
        return None
    if ref.startswith(("http://", "https://", "data:")):
        return ref
    if not os.path.exists(ref):
        raise APIError(f"找不到参考文件：{ref}")
    return to_data_uri(ref)


def download(url, dest):
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    if url.startswith("data:"):
        header, _, b64 = url.partition(",")
        with open(dest, "wb") as f:
            f.write(base64.b64decode(b64))
        return dest
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as f:
        f.write(resp.read())
    return dest


def pick_size(model, ratio):
    table = IMAGE_SIZES.get(model, {})
    return table.get(ratio) or next(iter(table.values()), "1024x1024")


def composite_reference(paths, dest, cell_h=512, pad=14, bg=(245, 245, 247)):
    """把多张参考图横向拼成一张「参考拼贴」，供**单参考图**的图像 API 同时参考多个主体/场景
    （多角色同框 + 场景一致性）。需要 Pillow；缺失或失败返回 None（调用方回退为单图）。"""
    try:
        from PIL import Image
    except Exception:
        return None
    imgs = []
    for p in (paths or []):
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        w = max(1, int(im.width * cell_h / max(1, im.height)))
        imgs.append(im.resize((w, cell_h)))
    if len(imgs) < 2:
        return None
    total_w = sum(i.width for i in imgs) + pad * (len(imgs) + 1)
    board = Image.new("RGB", (total_w, cell_h + pad * 2), bg)
    x = pad
    for im in imgs:
        board.paste(im, (x, pad))
        x += im.width + pad
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    try:
        board.save(dest)
    except Exception:
        return None
    return dest


# ---------- 图像 ----------

def image_sync(model, prompt, size=None, reference=None, seed=None):
    body = {"model": model, "prompt": prompt}
    if size:
        body["size"] = size
    if reference:
        body["reference"] = as_url(reference)
    if seed is not None:
        body["seed"] = seed
    resp = _request("POST", "/v1/image/sync", body)
    url = resp.get("url")
    if not url:
        raise APIError(f"image/sync 未返回 url：{resp}")
    return url


def image_async(model, prompt, size=None, reference=None, seed=None, poll_interval=4, max_wait=600):
    body = {"model": model, "prompt": prompt}
    if size:
        body["size"] = size
    if reference:
        body["reference"] = as_url(reference)
    if seed is not None:
        body["seed"] = seed
    resp = _request("POST", "/v1/image/async", body)
    task_id = resp.get("task_id")
    if not task_id:
        raise APIError(f"image/async 未返回 task_id：{resp}")
    waited = 0
    while waited < max_wait:
        st = _request("GET", "/v1/image/pending", query={"task_id": task_id})
        status = st.get("status")
        if status == "completed":
            return st.get("url")
        if status == "failed":
            raise APIError(f"图像生成失败：{st.get('error_message')}")
        time.sleep(poll_interval)
        waited += poll_interval
    raise APIError(f"图像生成超时（task_id={task_id}）")


# ---------- 视频 ----------

def build_video_content(prompt, reference_images=None,
                        prev_video=None, next_video=None, audio=None):
    """组装 /v1/video/create 的 content 数组（参考图驱动，不用首/尾帧）。

    - reference_images：列表，分镜图 + 角色设定图等，作为主体/构图参考。
    - prev_video/next_video：已托管的视频 URL（仅 http(s)，data URL 体积过大不建议）。
    - audio：音频 URL，驱动口型/节奏。
    """
    content = [{"type": "text", "text": prompt}]
    for ref in (reference_images or []):
        content.append({"type": "image", "url": as_url(ref), "role": "reference"})
    for v in (prev_video, next_video):
        if v:
            if not v.startswith(("http://", "https://")):
                raise APIError(f"参考视频必须是已托管的 http(s) URL：{v}（本地视频请先自行上传托管再传 URL）")
            content.append({"type": "video", "video_url": v})
    if audio:
        content.append({"type": "audio", "audio_url": as_url(audio)})
    return content


def video_create(content, duration, resolution, ratio, model=DEFAULT_VIDEO_MODEL,
                 generate_audio=True, watermark=True):
    body = {
        "model": model,
        "content": content,
        "duration": int(duration),
        "resolution": resolution,
        "ratio": ratio,
        "watermark": bool(watermark),
        "provider_specific": {"generate_audio": bool(generate_audio)},
    }
    resp = _request("POST", "/v1/video/create", body)
    task_id = resp.get("task_id")
    if not task_id:
        raise APIError(f"video/create 未返回 task_id：{resp}")
    return task_id


def video_poll(task_id, poll_interval=8, max_wait=1800, on_progress=None):
    waited = 0
    while waited < max_wait:
        st = _request("GET", "/v1/video/status", query={"id": task_id})
        status = st.get("status")
        if on_progress:
            on_progress(status, st.get("progress"))
        if status == "completed":
            url = st.get("video_url")
            if not url:
                raise APIError(f"视频已完成但缺少 video_url：{st}")
            return st
        if status == "failed":
            raise APIError(f"视频生成失败：{st.get('error_message')}")
        time.sleep(poll_interval)
        waited += poll_interval
    raise APIError(f"视频生成超时（task_id={task_id}）")


# ---------- 语音 ----------

def list_voices(voice_type="all"):
    return _request("POST", "/v1/get_voice", {"voice_type": voice_type})


def tts(text, voice_id, model=DEFAULT_TTS_MODEL, fmt="mp3", sample_rate=32000,
        speed=1.0, vol=1.0, pitch=0):
    body = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {"voice_id": voice_id, "speed": speed, "vol": vol, "pitch": pitch},
        "audio_setting": {"format": fmt, "sample_rate": sample_rate},
    }
    resp = _request("POST", "/v1/t2a_v2", body)
    audio_hex = (resp.get("data") or {}).get("audio")
    if not audio_hex:
        raise APIError(f"t2a_v2 未返回音频：{resp}")
    return bytes.fromhex(audio_hex)


# ---------- 成本预估 ----------

def estimate_image(model, count=1):
    return IMAGE_PRICE.get(model, 0.5) * count


def estimate_video(resolution, duration):
    return VIDEO_PRICE_PER_SEC.get(resolution, 1.0) * duration
