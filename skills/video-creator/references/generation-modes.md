# 阶段 3：视频生成模式

视频**以分镜图（+角色设定图）作参考**生成镜头内容。模式由输入自动判定，写入 `state.clips[].mode`。

> **不使用首/尾帧**（API「首尾帧和参考素材不能混用」）。本 skill 统一走参考图驱动。

> **默认工作流**：多 clip 硬切拼接；规划规则与时长见 [prompting-guide.md](prompting-guide.md)。`continue_prev` / `continue_next` 仅用户明确要求时使用。

| 模式 | 适用场景 | 传入参数 |
|------|----------|----------|
| `reference` | **默认**：参考分镜图 + 角色图生成镜头 | `--shots shot_01`（分镜图作参考）`--characters char_01`（角色锚点+图）`--reference a.png,b.png`（额外参考） |
| `text_to_video` | 从零生成，只有文字描述 | 只给 `--prompt` |
| `continue_prev` | **承接前置视频**（接着已有剧情往后拍） | `--prev-video <已托管 http(s) URL>` |
| `continue_next` | **续接后置视频**（往前补一段衔接到已有片段） | `--next-video <已托管 http(s) URL>` |
| `audio_driven` | **高级/非默认**：用已托管音频 URL 驱动口型与节奏；需用户自备音频 | `--audio https://.../voice.mp3` |

> `audio_driven` / `continue_*` 不在常规短剧工作流内；SKILL 默认只用 `reference` + 阶段4 硬切。

## 参考图驱动（主路径）

```bash
# 用分镜图 shot_01 + 出场角色作参考，生成 480p 样片
python scripts/gen_video.py --project P --id clip_01 --sample \
    --prompt "林夏推开便利店门，回头一笑；中景，人物约占画面 70%" \
    --shots shot_01 --characters char_01 --duration 5
```
- `--shots`：把对应分镜图作为参考图（镜头构图/内容的主要依据），放在参考列表最前。
- `--characters`：注入角色身份锚点（防性别/服装漂移）并把各角色设定图一并作参考。
- `--reference`：再追加任意参考图（逗号分隔）。
- 以上都作为 `reference` 传给 API，**不混用首/尾帧**。

## 承接 / 续接已有视频（非默认，慎用）

**常规短剧不要用此模式**——默认用多条独立 clip + 阶段4 硬切。仅当用户**明确要求**某镜必须承接上一段已生成视频的末尾时才用：

API 的 `video_url` 只接受**已托管的 http(s) 地址**：
- 承接：`--prev-video https://.../prev.mp4` + prompt 描述如何延续。
- 续接：`--next-video https://.../next.mp4`。
- 本地视频需先自行上传托管再给 URL（不再用抽帧+首尾帧的方式）。

## 一致性建议
- 同一角色多镜：`--characters` 注入身份锚点与各角色设定图。
- 镜头构图沿用分镜：`--shots` 指定对应分镜。
- prompt 写清人物/场景比例，跨镜用同一套措辞。
