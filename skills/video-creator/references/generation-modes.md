# 阶段 2：视频生成模式

确定本次片段「从什么生成」。模式由传给 `gen_video.py` 的输入决定，并自动写入 `state.clips[].mode`。

| 模式 | 适用场景 | 传入参数 |
|------|----------|----------|
| `text_to_video` | 从零生成，只有文字描述 | `--prompt` |
| `first_frame` | 指定开场画面 | `--first-frame img.png` |
| `last_frame` | 指定结尾画面 | `--last-frame img.png` |
| `first_last` | 同时锁定首尾，中间补全 | `--first-frame a.png --last-frame b.png` |
| `reference` | 用角色/场景图约束主体与风格 | `--reference c1.png,scene.png` |
| `continue_prev` | **承接前置视频**（接着已有剧情往后拍） | `--prev-video <URL>` 或抽末帧作 `--first-frame` |
| `continue_next` | **续接后置视频**（往前补一段衔接到已有片段） | `--next-video <URL>` 或抽首帧作 `--last-frame` |
| `audio_driven` | 用语音/音乐驱动口型与节奏 | `--audio voice.mp3` |

## 承接 / 续接已有视频

API 的 `video_url` 只接受**已托管的 http(s) 地址**。处理本地视频有两条路径：

1. **已托管视频**：直接 `--prev-video https://.../prev.mp4`（或 `--next-video`），可同时给 prompt 描述如何延续。
2. **本地视频**：先抽帧，再以首/尾帧约束（更稳、更省，推荐）：
   ```bash
   # 承接前一段：取它的末帧作为新片段的首帧
   python scripts/extract_frames.py --video prev.mp4 --out PROJECT/assets/refs --which last
   python scripts/gen_video.py --project PROJECT --id clip_02 \
       --prompt "延续上一镜，林夏走向柜台" --first-frame PROJECT/assets/refs/prev_last.png

   # 续接后一段：取后片的首帧作为新片段的尾帧
   python scripts/extract_frames.py --video next.mp4 --out PROJECT/assets/refs --which first
   python scripts/gen_video.py --project PROJECT --id clip_00 \
       --prompt "衔接镜头" --last-frame PROJECT/assets/refs/next_first.png
   ```
3. **首尾都给**：前段末帧作 `--first-frame`，后段首帧作 `--last-frame`，生成中间过渡，无缝衔接两段。

## 一致性建议
- 同一角色出现在多镜：把角色三视图/正面图作为 `--reference` 一并传入。
- 跨片段连贯：优先用「前段末帧 → 下段首帧」的链式约束，而非纯文生。
- 画幅 `ratio` 在整部短剧内保持一致（竖屏短剧用 `9:16`）。
