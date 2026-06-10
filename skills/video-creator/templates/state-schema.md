# state.json 结构说明

项目状态文件是对话轮次间的唯一事实来源。AI 和脚本读写 `./video-project/state.json`。

## 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_id` | string (uuid) | 项目唯一标识 |
| `brief` | object | 已确认的视频简报 |
| `characters` | array | 角色定义 |
| `scenes` | array | 场景定义 |
| `storyboard` | object | 含图像的分镜节拍 |
| `episodes` | array | 已生成视频历史 |
| `current_stage` | string | 当前工作流阶段 |
| `gates` | object | 批准标志 |

## brief

```json
{
  "title": "",
  "type": "",
  "style": "",
  "aspect_ratio": "16:9",
  "duration_target_sec": 10,
  "mood": "",
  "audience": "",
  "story_summary": ""
}
```

## characters[]

```json
{
  "id": "char_01",
  "name": "",
  "description": "",
  "views": {
    "front": "assets/char_01_front.png",
    "side": "assets/char_01_side.png",
    "back": "assets/char_01_back.png"
  },
  "reference_upload": null,
  "voice": {
    "source": "ai_recommended",
    "path": "",
    "description": ""
  },
  "status": "draft"
}
```

`status`：`draft` | `approved`

`voice.source`：`ai_recommended` | `user_upload` | `generated`

## scenes[]

```json
{
  "id": "scene_01",
  "name": "",
  "description": "",
  "image": "assets/scene_01.png",
  "reference_upload": null,
  "status": "draft"
}
```

## storyboard.beats[]

```json
{
  "id": "beat_01",
  "scene_id": "scene_01",
  "characters": ["char_01"],
  "action": "",
  "dialogue": "",
  "camera": "",
  "image": "assets/beat_01.png",
  "status": "draft"
}
```

## episodes[]

```json
{
  "episode": 1,
  "video_path": "output/ep01.mp4",
  "beats_used": ["beat_01", "beat_02"],
  "generated_at": "2026-06-08T12:00:00Z"
}
```

## current_stage

取值为：`brief`、`characters`、`scenes`、`storyboard`、`voice`、`preflight`、`generating`、`review`、`done`

## gates

```json
{
  "brief_approved": false,
  "characters_approved": false,
  "scenes_approved": false,
  "storyboard_approved": false,
  "voice_approved": false
}
```

运行 `generate_video.py` 前，五项均须为 `true`。
