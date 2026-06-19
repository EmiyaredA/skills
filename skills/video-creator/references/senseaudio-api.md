# SenseAudio API 参考（短剧生成相关）

本文件汇总脚本所依赖的 SenseAudio 接口，便于离线查阅。官方文档：https://docs.senseaudio.cn/

- **基础地址**：`https://api.senseaudio.cn`
- **鉴权**：请求头 `Authorization: Bearer <SENSEAUDIO_API_KEY>`
- **获取 Key**：https://senseaudio.cn/api-platform/api-key
- **环境变量**：`SENSEAUDIO_API_KEY`（优先）、`SENSEAUDIO_BASE_URL`（可选）
- **项目 Key**：项目根 `.sa_key`（用户在应用 `#config` 填写；`save_key.py` 写入），环境变量未设置时回退读取
- 请求/响应均为 `application/json`，UTF-8；错误含 `code` / `message`。

> 切勿把 Key 写入 `state.json` 或提交到 git。

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
| `senseaudio-image-2.0-260319` | 0.5 | 高分辨率、效果最佳；**样片与成片默认都用它**（参考图质量影响一致性） |
| `senseaudio-image-1.0-260319` | 0.2 | 最便宜；想降图像成本时可在设置里设为样片模型 |
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
  "duration": 10,
  "resolution": "720p",
  "ratio": "9:16",
  "watermark": true,
  "provider_specific": { "generate_audio": true }
}
```
- `role` ∈ `first_frame | last_frame | reference`。**⚠️ 首/尾帧与 reference 不能混用**（混用返回 400「首尾帧和参考素材不能混用」）。本 skill 统一只用 `reference`（分镜图+角色图），不发首/尾帧。
- `duration`：4–15 秒
- `resolution`：`480p | 720p | 1080p`
- `ratio`：`16:9 | 9:16 | 4:3 | 3:4 | 1:1`
- `video_url` 必须是 http(s) 已托管地址（Data URL 体积过大，本地视频请先自行上传托管再传 URL）。
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
