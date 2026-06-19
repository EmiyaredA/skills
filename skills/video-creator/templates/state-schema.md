# state.json 结构

`state.json` 是各轮对话之间的唯一事实来源，由 `project_utils.py` 读写。

## 顶层
| 字段 | 说明 |
|------|------|
| `project_id` | uuid |
| `title` | 作品标题 |
| `config` | 全局配置（见下） |
| `story` | 剧情：`logline`、`summary`、`beats[]`（阶段1 对齐时由助手填写，可选） |
| `characters[]` | 角色 |
| `scenes[]` | 场景 |
| `shots[]` | 分镜机位 |
| `clips[]` | 视频片段（样片/成片独立保留） |
| `exports[]` | 成片导出（按序拼接的整片） |
| `history[]` | 操作日志 |

## config
默认值见 `project_utils.default_config()`；用户在实时审核页（`serve_review.py`）的「设置」面板里随时改、即时落盘（`/api/config`）。
其中 `style`（视觉风格）会被 `gen_image`/`gen_video` 自动追加到每条提示词，保持全片风格统一：
```json
{ "ratio": "16:9", "style": "写实电影感",
  "image": { "model": "senseaudio-image-2.0-260319", "use_async": false },
  "video": { "model": "doubao-seedance-2-0-260128",
             "resolution_sample": "480p", "resolution_final": "720p",
             "duration_default": 5, "generate_audio": true, "watermark": true } }
```
API Key **不**存在 config/state 里：环境变量 `SENSEAUDIO_API_KEY` 优先，或用户在应用 `#config` 填入后写到项目根的 `.sa_key`（不进 git）。

## characters[]
```json
{ "id": "char_01", "name": "林夏", "prompt": "身份锚点描述",
  "gender": "女", "build": "娇小，比男主矮一头",
  "reference": "assets/refs/upload_char_01.png",
  "three_view": { "sheet": "assets/characters/char_01.png" },
  "image": "assets/characters/char_01.png",
  "review_decision": "通过", "review_note": "",
  "status": "draft|approved" }
```
默认路径为单张**三视图合图**（`sheet`）。仅用户明确要求分张时才有 `front`/`side`/`back`（3 倍价钱）。

## scenes[]
```json
{ "id": "scene_01", "name": "便利店", "prompt": "...",
  "image": "assets/scenes/scene_01.png",
  "review_decision": "通过", "status": "draft|approved" }
```

## shots[]（分镜机位）
```json
{ "id": "shot_01", "scene_id": "scene_01", "characters": ["char_01", "char_02"],
  "prompt": "中景，林夏推门", "image": "assets/shots/shot_01.png",
  "review_decision": "通过", "status": "draft|approved" }
```

## clips[]（视频片段）
样片与成片**各自独立**嵌套在 `sample` / `final` 下，互不覆盖：
```json
{ "id": "clip_01", "prompt": "...", "characters": ["char_01"],
  "shot_ids": ["shot_01"], "mode": "reference", "ratio": "16:9",
  "inputs": { "reference": ["assets/shots/shot_01.png", "assets/characters/char_01.png"],
              "prev_video": null, "next_video": null, "audio": null },
  "sample": { "resolution": "480p", "duration": 5, "status": "done",
              "local_path": "output/clip_01_sample.mp4", "task_id": "...", "cost_estimate": 2.5 },
  "final": { "resolution": "720p", "duration": 10, "status": "draft" },
  "review_decision": "通过", "status": "draft|approved" }
```
`mode` 常见为 `reference`（默认）。`continue_prev`/`continue_next`/`audio_driven` 为高级用法，见 [generation-modes.md](../references/generation-modes.md)。

## exports[]（成片导出）
```json
{ "id": "export_01", "title": "完整成片", "order": ["clip_01", "clip_02"],
  "ratio": "16:9", "local_path": "output/export_01.mp4", "status": "draft|done|failed" }
```
`order` 是按播放顺序排列的 clip id 列表（由助手按剧情排定），`concat_clips.py` 据此硬切拼接。

`status` / `review_decision`：用户在审核页「通过/需修改」写入 `review_decision`；`status` 为 `approved`（通过）或 `draft`（待改/未评）。
