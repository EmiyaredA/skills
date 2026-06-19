---
name: video-creator
description: >-
  帮助用户用 SenseAudio API 创作 AI 短剧视频。四阶段：①人设+场景 → ②分镜 → ③视频（480p样片→高清）→ ④导出。
  助手只备 plan 草稿（push_plan.py），生成由用户在 serve_review UI 触发；同一项目只启动一次服务，续作用 push_plan 勿重启。
  收到剧情时拆多个独立 clip（硬切、时长推荐 5/10/15s）。唯一前端 serve_review.py。
homepage: https://senseaudio.cn
metadata: {"audioclaw":{"emoji":"🎬","homepage":"https://senseaudio.cn","requires":{"bins":["python3"]},"primaryEnv":"SENSEAUDIO_API_KEY","optionalBins":["ffmpeg"],"notes":"API Key 也可由用户在应用 #config 写入项目 .sa_key"}}
license: Complete terms in LICENSE.txt
---

# AI 短剧创作（SenseAudio）

用 SenseAudio API 创作 AI 短剧。**唯一前端：`serve_review.py`**——首轮 `--daemon` 启动；对话框只对齐需求与备稿，生成/审核/重试由用户在 Web 应用内操作。

用户**没有终端**，脚本由**你（助手）**调用，且**仅限下节「助手协议」允许的动作**。

## 何时使用

AI 短剧、AI 视频、分镜、角色设计，或分步预览确认后再生成视频。

## 助手协议（最高优先级）

### 四条铁律

1. **没 Key → 引导 `#config`，绝不 mock**（`selftest.py` 除外）。
2. **只备稿，不触发生成。** 用户在 UI 点「▶ 开始生成」/「合成导出」/卡片「重试」。备完稿**立刻结束回合**；别说「已开始生成」——说「草稿已备好，请在页面点开始生成」。
3. **同一项目只启动一次服务。** 续作用 `push_plan.py`，**禁止**再 `--daemon`（旧进程占端口时会自增到 8766、8775…，用户链接失效）。
4. **阶段顺序不可逆**：设定(1) → 分镜(2) → 视频(3) → 导出(4)。默认只 push `status.py` 的 `next_stage` 任务，不要一次塞满多阶段草稿。

### 允许调用

| 动作 | 命令 |
|------|------|
| 建项目 | `init_project.py --parent … --title …` → 记 `$P` |
| **首轮**开服务 | `python3 scripts/serve_review.py --project "$P" --port 8765 --daemon [--plan plan.json]` |
| **续作**推草稿 | `push_plan.py --project "$P" --plan plan.json` |
| 检查服务 | `push_plan.py --project "$P" --check` |
| 读进度 | `status.py --project "$P"` |
| Key/环境/成本 | `check_key.py` · `ensure_env.py` · `estimate_cost.py` |
| 关服务 | `serve_review.py --project "$P" --stop`（仅用户要求时） |

### 禁止调用

`POST /api/generate` · `/api/generate-clips` · `/api/regenerate` · `/api/stop` · 直接运行 `gen_image.py`/`gen_video.py`/`concat_clips.py` · 轮询 `/api/tasks` · **续作时 `--daemon`**

### 工作流

**首轮**

1. `init_project.py` → `$P`
2. `serve_review --daemon [--plan plan.json]`（仅此一次）
3. `cat "$P/review/serve_url.txt"` → 给用户链接 + 深链（如 `#characters`）→ 结束回合

**续作**（用户说「继续」）

1. 复用同一 `$P`（不新建目录）
2. `status.py --json` 看 `next_stage`
3. `push_plan.py --check` → 若在跑：`push_plan.py --plan plan_stageN.json`；若 down：`--stop` 后**同端口** `--daemon`
4. 回复**同一 URL**（`serve_url.txt`），深链到对应阶段

**备稿后话术**：链接 + 阶段 +「请确认草稿后点 ▶ 开始生成；满意标记通过，再叫我备下一阶段」→ 结束回合。

> 服务端会自动跳过已通过/已有产出的 plan 项（`push_plan` 输出 `skipped`）；无需助手手动过滤。

## 应用速览

- 侧边栏四阶段；深链 `#config` `#characters` `#scenes` `#shots` `#clips` `#exports`
- plan → 草稿卡片 → 用户点生成 → worker 并行（默认 4 路，阶段门控）
- **停止**：取消排队任务；**正在生成的图像/视频会跑完**（导出 subprocess 可立即 terminate）
- clips 子页「一键生成」**仅处理尚未完成的样片/成片**；重出已有项用卡片「重新生成」

## 阶段与任务

| 阶段 | 任务 | 要点 |
|------|------|------|
| 1 | `characters` + `scenes` | [character-sheet.md](templates/character-sheet.md) · [environment-bible.md](templates/environment-bible.md)；有参考图时 prompt 从简 |
| 2 | `shots` | 1 shot ≈ 1 硬切；带 `characters`/`scene` |
| 3 | `clips` | 参考分镜+角色；样片/成片分子页；`duration` 推荐 5/10/15s |
| 4 | `exports` | `order` 硬切拼接；需 ffmpeg |

**clip 拆分**：收到剧情 → 节拍 → 每节拍 1 shot + 1 clip；硬切拼接。详见 [prompting-guide.md](references/prompting-guide.md)。

**对齐清单**：[brief.md](templates/brief.md)

## plan.json 示例

```json
{"story":{"logline":"…","beats":["节拍1"]},"tasks":[
  {"category":"characters","id":"char_01","name":"林夏","prompt":"…","gender":"女","build":"娇小"},
  {"category":"scenes","id":"scene_01","name":"便利店","prompt":"…"},
  {"category":"shots","id":"shot_01","prompt":"中景…","characters":"char_01","scene":"scene_01"},
  {"category":"clips","id":"clip_01","prompt":"…","characters":"char_01","shots":"shot_01","duration":10},
  {"category":"exports","id":"export_01","title":"完整成片","order":"clip_01,clip_02"}
]}
```

## 环境依赖

| 依赖 | 何时 | 安装 |
|------|------|------|
| ffmpeg | 阶段4 | `ensure_env.py --install --export` |
| Pillow | 多参考图拼贴（可选） | `ensure_env.py --install --image` |

## 常见问题

| 诉求 | 操作 |
|------|------|
| 继续 / 下一阶段 | `status.py` + `push_plan.py`，勿 `--daemon` |
| 服务挂了 | `push_plan --check` → `--stop` → 同端口 `--daemon` |
| 角色漂移 | 阶段1 UI 重出；分镜/视频带 `characters` |
| 续写剧情 | 新增 shot+clip；默认硬切 |

## 延伸阅读

- [senseaudio-api.md](references/senseaudio-api.md) · [generation-modes.md](references/generation-modes.md)
- [character-sheet.md](templates/character-sheet.md) · [environment-bible.md](templates/environment-bible.md)
- [prompting-guide.md](references/prompting-guide.md) · [state-schema.md](templates/state-schema.md)
