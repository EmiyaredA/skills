# 语音选择指南

在阶段 5 为角色配置语音，于视频生成前完成。

## 选项（按优先级）

1. **用户上传** — 用户提供参考音频（wav/mp3/m4a）
2. **TTS 生成** — 若已配置语音提供商，使用 `generate_voice.py`
3. **AI 推荐** — 仅文字描述（无音频文件）

## 用户上传参考语音时

- 保存至 `assets/{char_id}_voice_ref.{ext}`
- 在 `state.json` 中设置：

```json
"voice": {
  "source": "user_upload",
  "path": "assets/char_01_voice_ref.wav",
  "description": "用户提供的参考语音"
}
```

- 向用户确认：「已绑定您上传的参考语音，是否确认？」

## 无参考语音时（AI 推荐）

为每个有对白的角色提出语音方案：

| 字段 | 示例 |
|------|------|
| 性别 / 年龄段 | 女性，二十多岁 |
| 音色 | 温暖、好奇、略带气息感 |
| 语速 | 中等偏快 |
| 口音 | 标准普通话 / 轻微英式 |
| 参考对比 | 「类似纪录片旁白，但更年轻活泼」 |

逐角色展示推荐方案，**等待用户明确批准**。

在 `state.json` 中设置：

```json
"voice": {
  "source": "ai_recommended",
  "path": "",
  "description": "女性，二十多岁，温暖好奇音色，中等偏快语速，标准普通话"
}
```

## TTS 生成（可选）

若已配置 `voice` 提供商：

```bash
python scripts/generate_voice.py \
  --project ./video-project \
  --character char_01 \
  --text "示例台词，用于预览音色" \
  --voice-id default
```

批准前向用户播放或描述效果。

## 无对白的角色

语音配置可选。除非用户需要旁白音色，否则可跳过。

## 批准门禁

仅在以下条件满足后设置 `gates.voice_approved = true`：

- 每个有对白的角色均已配置 `voice.description` 或 `voice.path`
- 用户已明确确认语音选择

## 将语音传递给视频 API

- 若视频 API 接受音频参考：传入 `voice.path`
- 否则：在视频 prompt 中包含 `voice.description`，用于口型 / 语气指导
