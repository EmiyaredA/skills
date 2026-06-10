---
name: video-creator
description: >-
  引导用户通过分阶段确认的方式迭代创作 AI 视频。在生成视频前，先通过图像 API 产出角色三视图、场景图和分镜图供用户审核。
  适用于用户提到 AI 视频、视频生成、短片、分镜、角色设计、视频续写、剧本视频，
  或希望分步预览并确认后再生成视频内容的场景。即使用户未明确说「skill」，只要想制作 AI 视频就应使用本 skill。
license: Complete terms in LICENSE.txt
---

# AI 视频创作

结构化工作流，用于迭代式 AI 视频制作：确认需求 → 预生产资产（角色、场景、分镜）→ 生成视频 → 可选续写剧情。

作为主动引导者。**不得跳过确认门禁。** 在 `validate_assets.py` 通过之前，**不得调用 `generate_video.py`。**

## 何时提供此工作流

**触发条件：** 用户提到 AI 视频、短片、分镜、视频角色设计、视频续写，或分步创作视频。

**初始说明：** 向用户介绍八个阶段：

1. 需求简报 — 收集并确认需求
2. 角色预生产 — 通过图像 API 生成三视图
3. 场景预生产 — 生成环境图
4. 剧情分镜 — 逐格剧情 + 预览图
5. 语音配置 — 上传参考语音或由 AI 推荐
6. 预检门禁 — 资产完整性校验
7. 视频生成 — 单次 API 调用生成一集
8. 续写循环 — 可选的剧情延伸

询问用户是否采用此结构化工作流，或偏好自由模式。若拒绝，则按自由模式进行，但在生成视频前仍建议逐步确认。

## 约束参数

| 参数 | 推荐值 | 硬性限制 |
|------|--------|----------|
| 画幅比例 | 16:9 或 9:16 | 取决于 API 提供商 |
| 单集时长 | 5–15 秒 | 每次 API 调用 = 一集 |
| 角色数量 | 1–4 个 | 过多会降低一致性 |
| 每集分镜数 | 1–5 格 | 越少越稳定 |

详见 [references/video-params.md](references/video-params.md)。

## 快速参考

| 任务 | 命令 / 资源 |
|------|------------|
| 初始化项目 | `python scripts/init_project.py --project ./video-project` |
| 生成角色三视图 | `python scripts/generate_image.py --type character_three_view --id char_01 --prompt "..."` |
| 生成场景图 | `python scripts/generate_image.py --type scene --id scene_01 --prompt "..."` |
| 生成分镜预览图 | `python scripts/generate_image.py --type storyboard --id beat_01 --prompt "..."` |
| 生成语音（可选） | `python scripts/generate_voice.py --character char_01 --text "..."` |
| 生成前校验 | `python scripts/validate_assets.py --project ./video-project` |
| 生成视频 | `python scripts/generate_video.py --episode 1 --beats beat_01,beat_02` |
| 提取 QA 关键帧 | `python scripts/extract_keyframes.py --video output/ep01.mp4` |
| API 配置 | [references/api-config.md](references/api-config.md) |
| 图像 Prompt 规范 | [references/image-prompts.md](references/image-prompts.md) |
| 语音指南 | [references/voice-guide.md](references/voice-guide.md) |
| 状态文件结构 | [templates/state-schema.md](templates/state-schema.md) |
| 简报模板 | [templates/brief.md](templates/brief.md) |

在 `video-creator` skill 目录下运行脚本，或使用完整路径。安装依赖：`pip install -r requirements.txt`。

## 项目目录结构

`init_project.py` 会创建：

```
video-project/
├── state.json      # 唯一状态源
├── assets/         # 图像与语音文件
├── output/         # 生成的视频
└── docs/           # 简报与导出文档
```

每个阶段结束后更新 `state.json`。字段定义见 [templates/state-schema.md](templates/state-schema.md)。

## API 配置

首次生成前：

1. 请用户将 `config/providers.yaml.example` 复制为 `config/providers.yaml`
2. 用户设置环境变量 `IMAGE_API_KEY`、`VIDEO_API_KEY`（可选 `VOICE_API_KEY`）
3. 若提供商格式不清楚，阅读 [references/api-config.md](references/api-config.md)

**重要：** 切勿将 API Key 写入 `state.json` 或提交到 git。

---

## 阶段 1：需求简报

**目标：** 弥合用户构想与可执行规格之间的差距。

**操作步骤：**

1. 提出元问题：
   - 视频类型？（短片、广告、音乐视觉等）
   - 目标受众？
   - 期望的情绪 / 基调？
   - 画幅比例？（16:9 / 9:16）
   - 每集目标时长？
   - 视觉风格参考？
2. 鼓励用户倾倒信息 — 背景、剧情构思、约束、参考作品
3. 根据信息缺口提出 5–10 个澄清问题
4. 使用 [templates/brief.md](templates/brief.md) 起草简报 → 保存至 `video-project/docs/brief.md`
5. 更新 `state.json` → `brief` 字段，`current_stage: "brief"`

**向用户展示**简报摘要。

**门禁话术：** 请确认以上内容是否可以进入下一阶段，或告知需要修改的部分。

**退出条件：** 用户明确批准 → 设置 `gates.brief_approved: true`，`current_stage: "characters"`

---

## 阶段 2：角色预生产

**目标：** 为每个角色定义形象并生成三视图。

**操作步骤：**

1. 从简报中识别角色（若用户不确定，可建议数量）
2. 为每个角色使用 [templates/character-sheet.md](templates/character-sheet.md) 起草档案
3. 询问用户是否有参考图可上传
4. 阅读 [references/image-prompts.md](references/image-prompts.md) → 撰写 prompt
5. 为每个角色运行：

```bash
python scripts/generate_image.py \
  --project ./video-project \
  --type character_three_view \
  --id char_01 \
  --prompt "..." \
  --reference path/to/user_ref.png
```

6. 在 `state.json` → `characters[]` 中添加/更新条目，`status: "draft"`
7. **展示**角色档案 + 正面/侧面/背面图

**若用户上传参考图：** 保存至 `assets/{id}_ref.png`，设置 `reference_upload`，作为 `--reference` 传入。

**门禁话术：** 请确认以上内容是否可以进入下一阶段，或告知需要修改的部分。

**退出条件：** 用户批准所有角色 → 全部设为 `status: "approved"`，`gates.characters_approved: true`，`current_stage: "scenes"`

---

## 阶段 3：场景预生产

**目标：** 可视化故事中使用的每个环境。

**操作步骤：**

1. 从简报和故事大纲中列出场景
2. 使用 [templates/scene-sheet.md](templates/scene-sheet.md) 起草场景档案
3. 接受用户按场景上传的参考图
4. 为每个场景生成图像：

```bash
python scripts/generate_image.py \
  --project ./video-project \
  --type scene \
  --id scene_01 \
  --prompt "..."
```

5. 更新 `state.json` → `scenes[]`
6. **展示**场景图和描述

**门禁话术：** 请确认以上内容是否可以进入下一阶段，或告知需要修改的部分。

**退出条件：** 所有场景 `status: "approved"` → `gates.scenes_approved: true`，`current_stage: "storyboard"`

---

## 阶段 4：剧情分镜

**目标：** 用文本和预览图锁定剧情节拍。

**操作步骤：**

1. 将故事拆分为分镜节拍（每集 1–5 格）
2. 使用 [templates/storyboard.md](templates/storyboard.md) 起草 → `video-project/docs/storyboard.md`
3. 为每格生成预览图：

```bash
python scripts/generate_image.py \
  --project ./video-project \
  --type storyboard \
  --id beat_01 \
  --prompt "..."
```

4. 更新 `state.json` → `storyboard.beats[]`，关联 `scene_id`、`characters`、`action`、`dialogue`
5. **展示**完整分镜文本 + 预览图

**门禁话术：** 请确认以上内容是否可以进入下一阶段，或告知需要修改的部分。

**退出条件：** 所有节拍 `status: "approved"` → `gates.storyboard_approved: true`，`current_stage: "voice"`

---

## 阶段 5：语音配置

**目标：** 为每个有对白的角色配置语音。

阅读 [references/voice-guide.md](references/voice-guide.md)。

**操作步骤：**

1. 逐个询问有对白的角色：上传参考语音，还是由 AI 推荐？
2. **用户上传：** 保存至 `assets/{char_id}_voice_ref.*`，设置 `voice.source: "user_upload"`
3. **AI 推荐：** 提出性别、音色、语速、口音等建议 — 展示给用户
4. **可选 TTS：** 若已配置语音提供商，运行 `generate_voice.py` 并预览
5. 更新 `state.json` → 各角色的 `voice` 字段

**门禁话术：** 请确认以上内容是否可以进入下一阶段，或告知需要修改的部分。

**退出条件：** 用户确认所有语音 → `gates.voice_approved: true`，`current_stage: "preflight"`

---

## 阶段 6：预检门禁

**目标：** 在消耗视频 API 额度前验证所有资产。

**操作步骤：**

```bash
python scripts/validate_assets.py --project ./video-project
```

- **失败：** 列出错误，回到对应阶段修复，重新校验
- **通过：** 请用户做最终确认

**门禁话术：** 所有角色、场景、剧情和语音已确认。是否开始生成视频？

**退出条件：** 用户明确确认 → `current_stage: "generating"`

**重要：** 必须同时满足校验通过和用户确认，方可继续。

---

## 阶段 7：视频生成

**目标：** 每次 API 调用产出一集视频。

**操作步骤：**

```bash
python scripts/generate_video.py \
  --project ./video-project \
  --episode 1 \
  --beats beat_01,beat_02
```

1. 脚本自动校验门禁（除非使用 `--skip-validate`）
2. 输出：`output/ep01.mp4`，`state.json` → `episodes[]`
3. 提取 QA 关键帧：

```bash
python scripts/extract_keyframes.py --video ./video-project/output/ep01.mp4
```

4. 将关键帧与分镜对比 — 报告不一致之处
5. **展示**视频路径和 QA 观察结果
6. 设置 `current_stage: "review"`

---

## 阶段 8：续写循环

**目标：** 根据用户指示延伸剧情。

**门禁话术：** 是否基于当前剧情继续生成下一段？请描述希望发展的方向。

**若用户同意：**

1. 收集续写方向
2. 向 `storyboard.beats[]` 追加新节拍（`status: "draft"`）
3. 回到**阶段 4** 等待新节拍确认
4. 仅在有新对白角色时重新执行**阶段 5**
5. 重新执行**阶段 6** → **阶段 7**，使用下一集编号（`--episode 2` 等）

**若用户拒绝：** 设置 `current_stage: "done"`。可提供导出简报、分镜和剧集列表。

---

## 用户上传处理

| 资产类型 | 保存路径 | 用途 |
|----------|----------|------|
| 角色参考图 | `assets/{id}_ref.png` | 三视图生成的 `--reference` |
| 场景参考图 | `assets/{id}_ref.png` | 场景生成的 `--reference` |
| 语音参考 | `assets/{id}_voice_ref.*` | 写入 state 的 `voice.path` |

始终确认上传文件的用途：精确还原 vs. 风格参考。

---

## 门禁规则摘要

| 规则 | 执行方式 |
|------|----------|
| 不得跳阶段 | 每道门禁需用户明确批准 |
| 未校验不得生成视频 | `validate_assets.py` 必须返回 0 |
| 未确认不得生成视频 | 预检通过后用户须明确同意 |
| 每次调用一集 | 不得在一次 API 调用中批量生成多集 |
| 续写需重新确认 | 新节拍须重新走阶段 4 审批 |
| 草稿 vs 已批准 | 仅 `approved` 资产计入校验 |

## 修订流程

用户要求修改时：

1. 确定范围：简报 / 角色 / 场景 / 分镜 / 语音
2. 仅重新生成受影响的资产
3. 将受影响项设回 `status: "draft"`
4. 将相关门禁重置为 `false`，直至重新批准
5. 重新展示并等待确认

## 自由模式

用户拒绝结构化工作流时：

- 仍建议在生成视频前完成简报和分镜
- 仍在生成前运行 `validate_assets.py`
- 仍在生成角色/场景时展示中间图像

## 依赖

```bash
pip install -r requirements.txt
```

可选：PATH 中有 `ffmpeg` 可提取真实关键帧（无 ffmpeg 时有降级方案）。

## 延伸阅读

- [references/api-config.md](references/api-config.md) — API 提供商配置
- [references/image-prompts.md](references/image-prompts.md) — Prompt 撰写规范
- [references/video-params.md](references/video-params.md) — 分辨率、时长参数
- [references/voice-guide.md](references/voice-guide.md) — 语音选择指南
- [templates/state-schema.md](templates/state-schema.md) — state.json 字段说明
