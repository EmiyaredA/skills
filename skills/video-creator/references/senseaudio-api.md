# SenseAudio API 参考（短剧生成相关）

本文件汇总脚本所依赖的 SenseAudio 接口，便于离线查阅。官方文档：https://docs.senseaudio.cn/

- **基础地址**：`https://api.senseaudio.cn`
- **鉴权**：请求头 `Authorization: Bearer <SENSEAUDIO_API_KEY>`
- **获取 Key**：https://senseaudio.cn/api-platform/api-key
- **环境变量**：脚本读取 `SENSEAUDIO_API_KEY`（必填）、`SENSEAUDIO_BASE_URL`（可选）
- 请求/响应均为 `application/json`，UTF-8；错误含 `code` / `message`。

> 切勿把 Key 写入 `state.json` 或提交到 git。脚本只从环境变量读取。

---

## 图像生成

### 同步 `POST /v1/image/sync`
请求体：
```json
{ "model": "senseaudio-image-2.0-260319", "prompt": "...",
  "size": "1024x1024", "reference": "URL或DataURI(可选)", "seed": 123 }
```
响应：`{ "url": "https://..." }`

### 异步 `POST /v1/image/async` → 轮询 `GET /v1/image/pending?task_id=...`
- 创建返回 `{ "task_id": "..." }`
- 轮询返回 `status` ∈ `pending|completed|failed`；完成时取 `url`，失败时取 `error_message`。
- 高分辨率/大图建议走异步。

### 图像模型与价格（折扣价，元/张）
| 模型 | 价 | 说明 |
|------|----|------|
| `senseaudio-image-2.0-260319` | 0.5 | 高分辨率、效果最佳；**成片首选** |
| `senseaudio-image-1.0-260319` | 0.2 | 最便宜；**样片/草稿首选** |
| `doubao-seedream-5-0-260128` | 0.22 | 大尺寸输出 |
| `sensenova-u1-fast` | 0.5 | 信息图/排版 |

### 各模型 size 取值（节选常用画幅，完整见官方文档）
| 模型 | 1:1 | 16:9 | 9:16 |
|------|-----|------|------|
| image-2.0 | 1024x1024 | 1536x864 | 864x1536 |
| image-1.0 | 1328x1328 | 1664x928 | 928x1664 |
| seedream-5.0 | 2048x2048 | 2304x1728 | 1728x2304 |
| u1-fast | 2048x2048 | 2496x1664 | 1664x2496 |

- `reference` 传 URL 或 Data URI，用于风格/主体一致性约束。脚本会自动把本地图片转 Data URI。
- 单次只出 1 张（无 `n` 参数）。三视图分张时多次调用并复用 `seed` 保持一致。

---

## 视频生成

### 创建 `POST /v1/video/create`
```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    { "type": "text",  "text": "镜头描述..." },
    { "type": "image", "url": "...", "role": "first_frame" },
    { "type": "image", "url": "...", "role": "last_frame" },
    { "type": "image", "url": "...", "role": "reference" },
    { "type": "video", "video_url": "https://已托管/前置.mp4" },
    { "type": "audio", "audio_url": "..." }
  ],
  "duration": 8,
  "resolution": "720p",
  "ratio": "9:16",
  "watermark": true,
  "provider_specific": { "generate_audio": true }
}
```
- `role` ∈ `first_frame | last_frame | reference`
- `duration`：4–15 秒
- `resolution`：`480p | 720p | 1080p`
- `ratio`：`16:9 | 9:16 | 4:3 | 3:4 | 1:1`
- `video_url` 必须是 http(s) 已托管地址（Data URL 体积过大，本地视频请改用 `extract_frames.py` 抽帧）。
- 响应：`{ "task_id": "..." }`

### 查询 `GET /v1/video/status?id=<task_id>`
- `status` ∈ `pending | processing | completed | failed`
- 完成时取 `video_url`；另有 `progress`(0-100)、`duration`、失败时 `error_message`。

### 视频价格（折扣价，元/秒）
| 分辨率 | 元/秒 |
|--------|-------|
| 480p | 0.5 |
| 720p | 1.0 |
| 1080p | 3.1 |

> **省积分策略**：先用 480p 出样片确认效果，确认后再用 720p/1080p 出成片。

---

## 语音（TTS）

### 合成 `POST /v1/t2a_v2`
```json
{ "model": "senseaudio-tts-1.5-260319", "text": "台词", "stream": false,
  "voice_setting": { "voice_id": "female_0033_b", "speed": 1, "vol": 1, "pitch": 0 },
  "audio_setting": { "format": "mp3", "sample_rate": 32000 } }
```
- 响应：`data.audio` 为 **hex 编码音频**，脚本会 `bytes.fromhex` 后落盘。
- 格式：`mp3|wav|pcm|flac`；采样率：8000–44100。
- 价格：约 3.5 元/万字符（1 汉字=2 字符）。

### 列出音色 `POST /v1/get_voice`
```json
{ "voice_type": "all" }   // system | voice_clone | voice_generation | all
```
- 返回 `system_voice` / `voice_cloning` / `voice_generation` 数组，每项含 `voice_id`、`voice_name`、`description`。
- 声音克隆（3 秒素材即可）见官方 `guides/voice/custom`。
