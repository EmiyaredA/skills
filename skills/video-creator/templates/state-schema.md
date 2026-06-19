# state.json 结构

`state.json` 是各轮对话之间的唯一事实来源，由 `project_utils.py` 读写。

## 顶层
| 字段 | 说明 |
|------|------|
| `project_id` | uuid |
| `title` | 作品标题 |
| `created_at` / `updated_at` | ISO 时间戳（系统自动写入） |
| `config` | 全局配置（见下） |
| `story` | 剧情元数据：`logline`、`summary`、`beats[]`（可选；由 plan 顶层 `story` 同步） |
| `characters[]` | 角色 |
| `scenes[]` | 场景 |
| `shots[]` | 分镜机位 |
| `clips[]` | 视频片段（样片/成片独立保留） |
| `exports[]` | 成片导出（按序拼接的整片） |
| `history[]` | 操作日志 |

## plan 任务字段 ↔ state 资产字段

助手写 `plan.json` 时用左列；生成完成后 `state.json` 用右列：

| plan 任务字段 | state 资产字段 |
|--------------|---------------|
| `"characters": "char_01"` 或 `"char_01,char_02"` | `"characters": ["char_01"]` 数组 |
| `"scene": "scene_01"` | `"scene_id": "scene_01"` |
| `"shots": "shot_01"` | `"shot_ids": ["shot_01"]` |
| `"order": "clip_01,clip_02"` | `"order": ["clip_01", "clip_02"]` |
| `"references": ["path.png"]` | 角色/分镜：`references[]`；clip：`inputs.reference[]` |

入队时 `reference`/`shot` 等历史别名会自动规范为 `references`/`shots`。

## config
默认值见 `project_utils.default_config()`；用户在实时审核页的「设置」面板修改（`/api/config`）。
`style` 会被 `gen_image`/`gen_video` 自动追加到每条提示词：
```json
{ "ratio": "16:9", "style": "",
  "image": { "model": "senseaudio-image-2.0-260319", "use_async": false },
  "video": { "model": "doubao-seedance-2-0-260128",
             "resolution_sample": "480p", "resolution_final": "720p",
             "duration_default": 5, "generate_audio": true, "watermark": true } }
```
常见 `style` 值：写实电影感、日系治愈手绘风、国风动画…

API Key **不**存在 config/state：环境变量 `SENSEAUDIO_API_KEY` 优先，或用户在 `#config` 填入后写到 `.sa_key`。

## characters[]（助手可写字段 + 系统填充）
```json
{ "id": "char_01", "name": "林夏", "prompt": "身份锚点描述",
  "gender": "女", "build": "娇小，比男主矮一头",
  "references": ["assets/refs/upload_char_01.png"],
  "three_view": { "sheet": "assets/characters/char_01.png" },
  "image": "assets/characters/char_01.png",
  "model": "senseaudio-image-2.0-260319",
  "review_decision": "通过", "review_note": "",
  "status": "draft|approved" }
```
`review_decision` 合法值：`通过` | `需修改`（用户在审核页写入）。

## scenes[]
```json
{ "id": "scene_01", "name": "便利店", "prompt": "...",
  "image": "assets/scenes/scene_01.png",
  "review_decision": "通过", "status": "draft|approved" }
```

## shots[]
```json
{ "id": "shot_01", "scene_id": "scene_01", "characters": ["char_01", "char_02"],
  "prompt": "中景，林夏推门", "image": "assets/shots/shot_01.png",
  "review_decision": "通过", "status": "draft|approved" }
```

## clips[]
样片与成片**各自独立**嵌套在 `sample` / `final` 下：
```json
{ "id": "clip_01", "prompt": "...", "characters": ["char_01"],
  "shot_ids": ["shot_01"], "mode": "reference", "ratio": "16:9",
  "inputs": { "reference": ["assets/shots/shot_01.png", "assets/characters/char_01.png"],
              "prev_video": null, "next_video": null, "audio": null },
  "sample": { "resolution": "480p", "duration": 5, "status": "done",
              "local_path": "output/clip_01_sample.mp4", "task_id": "...", "cost_estimate": 2.5,
              "video_url": "https://..." },
  "final": { "resolution": "720p", "duration": 10, "status": "draft" },
  "review_decision": "通过", "status": "draft|approved" }
```
`duration` 推荐 5/10/15 秒；API/UI 支持 4–15。高级模式见 [generation-modes.md](../references/generation-modes.md)。

## exports[]
```json
{ "id": "export_01", "title": "完整成片", "order": ["clip_01", "clip_02"],
  "ratio": "16:9", "local_path": "output/export_01.mp4", "status": "draft|done|failed" }
```
