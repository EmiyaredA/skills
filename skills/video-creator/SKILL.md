---
name: video-creator
description: >-
  帮助用户用 SenseAudio API 创作 AI 短剧视频。四阶段流水：①人设+场景 → ②分镜 → ③视频成片（480p 样片→高清）
  → ④导出拼接。助手只备 plan 草稿（push_plan.py / POST /api/plan），生成由用户在 serve_review UI 点「开始生成」触发；同一项目只启动一次服务，续作用 push_plan 勿重启。
  收到剧情时先拆多个独立 clip（硬切、时长 5/10/15s）。唯一前端 serve_review.py 本地 Web 应用。
  适用于 AI 短剧、视频生成、分镜、角色设计等场景。
homepage: https://senseaudio.cn
metadata: {"audioclaw":{"emoji":"🎬","homepage":"https://senseaudio.cn","requires":{"bins":["python3"]},"primaryEnv":"SENSEAUDIO_API_KEY","optionalBins":["ffmpeg"],"notes":"API Key 也可由用户在应用 #config 写入项目 .sa_key"}}
license: Complete terms in LICENSE.txt
---

# AI 短剧创作（SenseAudio）

用 SenseAudio 图像/视频 API 创作 AI 短剧。**唯一前端：`serve_review.py` 本地 Web 应用**——会话一开始就 `--daemon` 启动并打开；**对话框只负责对齐需求与备稿，生成/审核/重试全在应用内由用户操作**。

本 skill 跑在用户本机（SoWork/audioclaw）。用户**没有终端**，所有脚本由**你（助手）**调用——但**仅限「准备」类脚本**，见下节。

## 何时使用

用户提到 AI 短剧、AI 视频、视频生成、分镜、角色设计，或想分步预览确认后再生成视频。

## 三条最高优先级规则

1. **没 Key 就引导去 `#config`，绝不 mock。** Key 来源：环境变量 `SENSEAUDIO_API_KEY` > 项目 `.sa_key`。严禁用 `--mock` 交付（仅 `selftest.py` 自检）。
2. **你只「准备」plan 草稿；触发生成是用户的专属动作。** 用户在 UI 点「▶ 开始生成」/「合成导出」/卡片「重试」才跑。备完稿后**立刻结束回合**，把链接交给用户，**不要**替用户点生成、不要轮询等完成。别说「已开始生成」「正在生成中」——应说「草稿已备好，请在页面点开始生成」。
3. **同一项目只启动一次服务，续作勿重启。** 首轮 `--daemon` 后全程复用 `$P/review/serve_url.txt` 同一链接；用户说「继续」时用 `push_plan.py` 往**已在跑**的服务推下一阶段草稿。**禁止**为备稿再次 `--daemon`（旧进程仍占端口时会自增到 8766、8775…，用户浏览器链接失效）。
4. **阶段顺序不可逆**：人设+场景(1) → 分镜(2) → 视频(3) → 导出(4)。队列阶段门控；分阶段推进，不要一次塞满。

## 助手职责边界（严禁越权）

**你的职责**：对齐需求 → 写 `plan.json` → **首轮** `serve_review --daemon [--plan …]` **或续作** `push_plan.py` → 给用户**同一个** URL → **结束回合**。

**只允许你调用**（准备 / 读状态 / 环境）：

| 动作 | 方式 |
|------|------|
| 建项目 | `init_project.py` |
| **首轮**开前端 | `serve_review.py --project "$P" --port 8765 --daemon [--plan plan.json]`（**每个项目只执行一次**） |
| **续作**备草稿 | `push_plan.py --project "$P" --plan plan.json`（**勿再 --daemon**） |
| 检查服务是否在跑 | `push_plan.py --project "$P" --check` → 读 `SERVE_OK:` 后的 URL |
| 关前端 | `serve_review.py --project "$P" --stop`（仅用户要求关闭时） |
| 读进度 | `status.py --project "$P"`（读 `state.json`，**不**轮询 `/api/tasks`） |
| Key/环境/成本 | `check_key.py`、`ensure_env.py`、`estimate_cost.py` |

**严禁你调用**（即使用 curl/fetch/脚本也不行；除非用户**明确口头要求**你代点某一单项「重试」，仍优先让用户自己在 UI 操作）：

| 禁止 | 原因 |
|------|------|
| `POST /api/generate` | 用户在 UI 点「▶ 开始生成」 |
| `POST /api/generate-clips` | 用户在「样片/成片生成」子页触发 |
| `POST /api/regenerate` | 用户在卡片点「重新生成/重试」 |
| `POST /api/stop` | 用户在 UI 点「停止」 |
| 直接运行 `gen_image.py` / `gen_video.py` / `concat_clips.py` | 由 serve_review worker 或用户在 UI 触发（`selftest.py` 除外） |
| 轮询 `/api/tasks` 等待生成完成 | 进度在浏览器里看；你只在用户说「继续/做完了吗」时用 `status.py` 读盘 |
| 为续作再次 `--daemon` | 会占新端口、旧链接失效；用 `push_plan.py` |
| `serve_review --daemon --plan` 备下一阶段 | 同上；续作用 `push_plan.py` |

**备稿后的标准话术**：给出 `serve_url.txt` 链接 + 当前阶段 +「请在页面确认草稿后点 ▶ 开始生成；满意后标记通过，再叫我备下一阶段」→ **结束回合，不要接着跑生成。**

## 启动协议

### 首轮（新建项目，只做一次）

1. `init_project.py` 建工作目录，记为 `$P`。
2. **只此一次** `--daemon` 常驻：
   ```bash
   python3 scripts/serve_review.py --project "$P" --port 8765 --daemon [--plan plan.json]
   ```
   不要用 `run_in_background`；输出写 `review/serve.log`。
3. 读 URL：`sleep 1; cat "$P/review/serve_url.txt"`（若 8765 被占会自增，以文件为准）。
4. 把链接放进回复 → 告知用户点「开始生成」→ **结束回合**。

### 续作（用户说「继续」/备下一阶段）—— **禁止再 --daemon**

1. **复用同一 `$P`**（从对话上下文取项目路径，不要新建目录）。
2. 先 `python scripts/status.py --project "$P"` 看 `next_stage`。
3. 检查服务：`python scripts/push_plan.py --project "$P" --check`
   - 若在跑 → 写下一阶段 `plan.json` → `python scripts/push_plan.py --project "$P" --plan plan.json`
   - 若不在跑（`SERVE_DOWN`）→ **仅此时**可 `--stop` 清陈旧 pid 后，用**同一 `--port`** 重新 `--daemon`（优先读旧 `serve_url.txt` 里的端口号）。
4. 回复里给**同一个 URL**（`cat "$P/review/serve_url.txt"`），深链到对应阶段如 `#shots`。**不要给新端口链接。**

> **为何不能重复 --daemon？** 旧服务进程通常还在，新启动会从 `--port` 起找空闲端口（8765→8766→…→8775），用户浏览器仍开着旧链接，体验混乱。

## 应用速览

- 侧边栏四阶段 + 卡片；深链 `#config` `#characters` `#scenes` `#shots` `#clips` `#exports`。
- 你写 plan → 草稿卡片 → 用户点生成 → worker 并行（默认 4 路，阶段门控）。
- 卡片可改 prompt/参考图/模型、「通过/需修改」、单项/全部停止、重试。
- 停止服务：侧边栏「关闭服务」或 `serve_review.py --project "$P" --stop`。

## 阶段与任务类型

| 阶段 | 任务 | 要点 |
|------|------|------|
| 1 设定 | `characters` + `scenes` | 人设 [character-sheet.md](templates/character-sheet.md) 设定资料卡；场景 [environment-bible.md](templates/environment-bible.md) Environment Bible（六模块空镜合图）；有参考图时 `prompt` 从简；`gender`/`build`/`style_ref` |
| 2 分镜 | `shots` | 1 shot ≈ 1 硬切镜头；带 `characters`/`scene`；参考图自动注入 |
| 3 视频 | `clips` | 参考分镜+角色图；样片/成片分子页独立保留；不写 `sample` 进 plan |
| 4 导出 | `exports` | 按 `order` 硬切拼接；需 ffmpeg（见「环境依赖」） |

**参考图**：分镜/视频任务写 `characters`(+`scene`) 决定身份锚点；服务自动注入已完成阶段1/2 的图。多角色分镜无 Pillow 时回退单参考图。**比例**：`build` + 每条分镜/视频 prompt 显式写人物间、人与场景大小关系。**风格**：`config.style` 自动追加到每条 prompt。

**clip 拆分（收到用户剧情必做）**：先拆多条独立 clip（通常 1 clip = 1 shot），阶段4 **硬切**拼接。`duration` **推荐** 5/10/15 秒（API/UI 支持 4–15）。详情见 [references/prompting-guide.md](references/prompting-guide.md)。

## 续作

用户说「继续」→ `status.py` 读 `next_stage` → **`push_plan.py` 推草稿到已在跑的服务**（见上节「续作」协议）。**绝不** `--daemon` 重启、**绝不** `/api/generate`、**绝不**重推已通过资产。回复沿用 `$P/review/serve_url.txt` 同一链接。

## 环境依赖

| 依赖 | 何时 | 安装 |
|------|------|------|
| ffmpeg/ffprobe | 阶段4 导出 | `python scripts/ensure_env.py --install --export`（brew/apt 等） |
| Pillow | 阶段2 多参考图拼贴（可选） | `python scripts/ensure_env.py --install --image`（pip） |

导出前先看 `status.py` 输出的 `env.export_ready`；为 false 再 install。应用内「合成导出」与 `concat_clips.py` 也会尝试自动装 ffmpeg。

## 阶段 0：建目录 + 开应用

```bash
python scripts/init_project.py --parent /abs/sa_drama --title "<标题>"   # → PROJECT:<路径> 记为 $P
python3 scripts/serve_review.py --project "$P" --port 8765 --daemon
```

每轮对话新建 `$P`；**同一轮对话内全程复用同一 `$P` 与同一 serve URL**。对齐清单见 [templates/brief.md](templates/brief.md)。

## 阶段 1：人设 + 场景

用 brief 对齐需求。人设图按 [character-sheet.md](templates/character-sheet.md)、场景图按 [environment-bible.md](templates/environment-bible.md) 的布局生成（脚本自动追加资料卡/Environment Bible；画风由参考图 / `prompt` / `config.style` 决定）。参考图**必须对应正确资产**（逐张确认，或让用户在卡片上传）。plan 只放 `characters` + `scenes`。可先备 `shots`/`clips` 草稿预览全貌，**生成仍按阶段门控，由用户在 UI 触发**。

## 阶段 2：分镜

每镜一张机位图，与 clip 一一对应。prompt 写景别/机位/动作/比例。详见 [references/prompting-guide.md](references/prompting-guide.md) 图像/分镜章节。`POST /api/plan` 备 `shots` 草稿后交给用户生成。

## 阶段 3：视频

备 `clips`（`shots`、`characters`、`duration`）草稿。**用户**在「样片生成」点「开始生成」出 480p，满意后在「成片生成」出 720p/1080p。样片/成片互不覆盖。

## 阶段 4：导出

`env.export_ready` 为 true 后，`POST /api/plan` 备 `exports`（`order` 为 clip id 有序列表）。用户点「合成导出」。

## plan.json 示例

```json
{"story":{"logline":"…","summary":"…","beats":["节拍1","节拍2"]},"tasks":[
  {"category":"characters","id":"char_01","name":"林夏","prompt":"粉色长卷发，米色针织开衫配白衬衫，温柔表情","gender":"女","build":"娇小"},
  {"category":"scenes","id":"scene_01","name":"便利店","prompt":"深夜便利店，收银区与货架通道，关联门外街道；雨后冷白荧光"},
  {"category":"shots","id":"shot_01","prompt":"中景…","characters":"char_01","scene":"scene_01"},
  {"category":"clips","id":"clip_01","prompt":"中景固定机位…","characters":"char_01","shots":"shot_01","duration":10},
  {"category":"exports","id":"export_01","title":"完整成片","order":"clip_01,clip_02"}
]}
```

## 脚本速查

**助手可调用**：

| 任务 | 命令 |
|------|------|
| 初始化 | `python scripts/init_project.py --parent /abs/sa_drama --title "..."` |
| 进度 | `python scripts/status.py --project "$P"` |
| **首轮**启动 | `python3 scripts/serve_review.py --project "$P" --port 8765 --daemon [--plan plan.json]` → `cat review/serve_url.txt` |
| **续作**推 plan | `python scripts/push_plan.py --project "$P" --plan plan.json` |
| 检查服务 | `python scripts/push_plan.py --project "$P" --check` |
| 停止 | `python3 scripts/serve_review.py --project "$P" --stop` |
| 检查 Key | `python scripts/check_key.py --project "$P"`（2=缺 Key） |
| 环境 | `python scripts/ensure_env.py --install --export` |
| 成本 | `python scripts/estimate_cost.py --project "$P"` |

**禁止助手直接调用**（由 serve_review UI/worker 触发；文档示例见 [references/prompting-guide.md](references/prompting-guide.md) 仅供理解参数）：

`gen_image.py` · `gen_video.py` · `concat_clips.py` · `POST /api/generate` · `POST /api/generate-clips` · `POST /api/regenerate`

角色默认单张合图；分张 `--views` 仅用户明确要求（3 倍价）。

## 项目结构

```
<总目录>/<标题>_<时间>_<随机>/
  state.json   .sa_key   assets/   output/   review/   docs/
```
详见 [templates/state-schema.md](templates/state-schema.md)。

## 修改 / 常见问题

| 诉求 | 操作 |
|------|------|
| 用户说「继续」 | `status.py` + `push_plan.py`，**不要** `--daemon` 重启 |
| 链接打不开 / 服务挂了 | `push_plan.py --check`；确认 down 后 `--stop` 再同端口 `--daemon` |
| 角色漂移/性别错 | 阶段1 在 UI 重出；分镜/视频带 `characters`，prompt 写清人数与动作 |
| 构图不对 | 阶段2 改分镜 → 用户在 UI 重出 clip |
| 画质/时长 | 阶段3 用户在 UI 调参数重出 |
| 续写剧情 | 新增 shot+clip；默认硬切，勿假设丝滑衔接 |
| 版权拦截 | 换原创参考图重做角色，勿用 IP 官方图 |

## 延伸阅读

- [references/senseaudio-api.md](references/senseaudio-api.md) — API、价格
- [references/generation-modes.md](references/generation-modes.md) — 视频模式
- [templates/character-sheet.md](templates/character-sheet.md) — 人设设定资料卡默认模板
- [templates/environment-bible.md](templates/environment-bible.md) — 场景 Environment Bible 默认模板
- [references/prompting-guide.md](references/prompting-guide.md) — 提示词、clip 拆分、一致性
- [templates/brief.md](templates/brief.md) — 阶段1 对齐清单
