# state.json 结构

`state.json` 是各轮对话之间的唯一事实来源，由 `project_utils.py` 读写。

## 顶层
| 字段 | 说明 |
|------|------|
| `project_id` | uuid |
| `title` | 作品标题 |
| `phase` | `align`（对齐需求）/ `mode`（确定模式）/ `generate`（生成） |
| `config` | 全局配置（见下） |
| `story` | 剧情：`logline`、`summary`、`beats[]` |
| `characters[]` | 角色 |
| `scenes[]` | 场景 |
| `shots[]` | 分镜机位 |
| `clips[]` | 视频片段（样片/成片） |
| `history[]` | 操作日志 |

## config
默认值见 `project_utils.default_config()`；用户在实时审核页（`serve_review.py`）的「设置」面板里随时改、即时落盘（`/api/config` → `apply_config`）：
```json
{ "ratio": "9:16", "style": "写实电影感",
  "image": { "model_final": "senseaudio-image-2.0-260319",
             "model_sample": "senseaudio-image-1.0-260319", "use_async": false },
  "video": { "model": "doubao-seedance-2-0-260128",
             "resolution_sample": "480p", "resolution_final": "1080p",
             "duration_default": 5, "generate_audio": true, "watermark": true },
  "audio": { "tts_model": "senseaudio-tts-1.5-260319", "voice_id": "",
             "format": "mp3", "speed": 1.0 } }
```
API Key **不**存在 config/state 里：走环境变量 `SENSEAUDIO_API_KEY`，或用户在应用 `#config` 填入后写到项目根的 `.sa_key`（不进 git）。

## characters[]
```json
{ "id": "char_01", "name": "林夏", "prompt": "身份锚点描述",
  "reference": "用户参考图路径(可选)",
  "three_view": { "front": "assets/characters/char_01_front.png",
                  "side": "...", "back": "...", "sheet": "(整张三视图，二选一)" },
  "image": "主用图",
  "voice": { "source": "tts", "voice_id": "female_0033_b",
             "sample_text": "...", "sample": "assets/voices/char_01.mp3" },
  "status": "draft|approved" }
```

## scenes[]
```json
{ "id": "scene_01", "name": "便利店", "prompt": "...",
  "image": "assets/scenes/scene_01.png", "status": "draft|approved" }
```

## shots[]（分镜机位）
```json
{ "id": "shot_01", "scene_id": "scene_01", "characters": ["char_01"],
  "prompt": "中景，林夏推门", "image": "assets/shots/shot_01.png",
  "status": "draft|approved" }
```

## clips[]（视频片段）
```json
{ "id": "clip_01", "kind": "sample|final",
  "mode": "first_frame|first_last|continue_prev|...",
  "prompt": "...", "shot_ids": ["shot_01"],
  "inputs": { "first_frame": "", "last_frame": "", "reference": [],
              "prev_video": "", "next_video": "", "audio": "" },
  "resolution": "480p", "duration": 5, "ratio": "9:16",
  "task_id": "...", "video_url": "...", "local_path": "output/clip_01_sample.mp4",
  "cost_estimate": 2.5, "status": "draft|generating|done|failed" }
```

`status`：草稿资产为 `draft`，经用户在审核页确认后置 `approved`。修订时把受影响项设回 `draft`。
