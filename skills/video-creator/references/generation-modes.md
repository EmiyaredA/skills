# 阶段 3：视频生成模式

视频**以分镜图（+角色设定图）作参考**生成镜头内容。模式由传给 `gen_video.py` 的输入自动判定，写入 `state.clips[].mode`。

> ⚠️ **不使用首/尾帧**：SenseAudio 视频 API「首尾帧和参考素材不能混用」（混用会 400）。本 skill 统一走**参考图驱动**，
> 把分镜图、角色设定图都作为 `reference` 传入；需要镜头开场画面就把对应分镜图作参考。

| 模式 | 适用场景 | 传入参数 |
|------|----------|----------|
| `reference` | **默认**：参考分镜图 + 角色图生成镜头 | `--shots shot_01`（分镜图作参考）`--characters char_01`（角色锚点+图）`--reference a.png,b.png`（额外参考） |
| `text_to_video` | 从零生成，只有文字描述 | 只给 `--prompt` |
| `continue_prev` | **承接前置视频**（接着已有剧情往后拍） | `--prev-video <已托管 http(s) URL>` |
| `continue_next` | **续接后置视频**（往前补一段衔接到已有片段） | `--next-video <已托管 http(s) URL>` |
| `audio_driven` | 用语音/音乐驱动口型与节奏 | `--audio voice.mp3` |

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

## 承接 / 续接已有视频

API 的 `video_url` 只接受**已托管的 http(s) 地址**：
- 承接：`--prev-video https://.../prev.mp4` + prompt 描述如何延续。
- 续接：`--next-video https://.../next.mp4`。
- 本地视频需先自行上传托管再给 URL（不再用抽帧+首尾帧的方式）。

## 一致性建议
- 同一角色出现在多镜：`--characters` 注入，自动带各角色设定图作参考。
- 镜头构图沿用分镜图：`--shots` 指定该 clip 对应的分镜。
- 在 prompt 里写清人物之间、人物与场景/道具的**比例**，并跨镜用同一套措辞。
- 画幅 `ratio` 在整部短剧内保持一致（竖屏短剧用 `9:16`）。
