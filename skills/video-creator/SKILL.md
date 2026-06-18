---
name: video-creator
description: >-
  帮助用户用 SenseAudio API 创作 AI 短剧视频。三阶段循环：①对齐需求（角色三视图、音色、场景、
  故事、机位，可反复确认并接收用户参考图/视频/音频）→ ②确定生成模式（承接前置/后置视频，或首/尾/首尾帧）
  → ③先出低配样片确认效果，再出成片。每次生成都产出可交互的 HTML 审核页供用户查看并反馈。
  适用于 AI 短剧、AI 视频生成、分镜、角色设计、视频续写/续接、首尾帧生成等场景。
  即使用户未明确说「skill」，只要想做 AI 短剧/视频就应使用本 skill。
homepage: https://senseaudio.cn
metadata: {"audioclaw":{"emoji":"🎬","homepage":"https://senseaudio.cn","requires":{"bins":["python3"],"env":["SENSEAUDIO_API_KEY"]},"primaryEnv":"SENSEAUDIO_API_KEY","optionalBins":["ffmpeg"]}}
license: Complete terms in LICENSE.txt
---

# AI 短剧创作（SenseAudio）

用 SenseAudio 的图像 / 视频 / 语音 API 创作 AI 短剧。**整套交互只有一个前端：`serve_review.py` 这个本地实时 Web 应用。**
会话一开始你就把它启动并打开，它就是用户从头到尾用的界面；**对话框只作为指挥/沟通渠道**，所有配置、生成、查看、确认都在这个 Web 应用里完成。

> ## ❗最高优先级规则：没有 Key 就让用户在应用里填，绝不 mock
> 任何真实生成前，必须已配置 API Key（环境变量 `SENSEAUDIO_API_KEY` 或项目 `.sa_key`）。
> **没有 Key 时唯一正确动作：把用户引导到应用的配置区 `…/#config` 填入 Key**（应用里有 Key 输入框，保存即写 `.sa_key`、即时生效）。
> **严禁**：用 `--mock` 顶替、把 mock 占位文件当作品交付、或"先用 mock 跑通流程"。`--mock` 只属于 `selftest.py` 离线自检。
> 没有 Key 时，应用里的生成任务会立刻标「失败」并提示去 `#config` 配 Key——不要退化成 mock。

## 何时使用

用户提到 AI 短剧、AI 视频、视频生成、分镜、角色设计、视频续写/续接、首尾帧生成，或想分步预览确认后再生成视频。

## 唯一前端：实时 Web 应用 `serve_review.py`（务必先读）

本 skill 运行在 SoWork/audioclaw 工作区，跑在用户本机。用户**没有终端**，所有脚本由**你（助手）**调用。
**会话开始就启动这个应用并打开**，之后整个流程都在它里面进行：

### ❗启动协议（务必照做，否则页面打不开 / 会话卡死 / 服务被回收）
1. 先 `init_project.py` 建好工作目录。
2. **以「分离常驻」方式启动**——命令以 `& disown` 结尾，会立即返回，且进程独立存活、**不随本回合结束被回收**：
   ```bash
   nohup python3 scripts/serve_review.py --project <工作目录> --port 8765 [--plan <工作目录>/review/plan.json] \
     > <工作目录>/review/serve.log 2>&1 & disown
   ```
   - **绝不要前台运行**（`serve_forever` 不返回 → 本回合永久卡在「思考中」）。
   - **也不要用 `run_in_background`**：本工作区可能在回合/会话结束时回收它，导致页面突然 `ERR_CONNECTION_REFUSED`（后端没了）。`nohup … & disown` 才能让它一直活着。
3. **读取真实 URL——不要假设就是 8765**！8765 常被别的程序占用，服务会自增端口（8766…）。启动后：
   ```bash
   sleep 1; cat <工作目录>/review/serve_url.txt   # → http://127.0.0.1:<实际端口>/
   ```
4. 把这个**真实链接**作为可点击链接放进回复（例：`[打开创作台 ↗](http://127.0.0.1:8766/#config)`），然后结束本回合，不阻塞等待。
5. **如何拿到结果**：用户在页面点「继续 / 重做这一批」后，应用会写 `review/review_result.json` 并自行退出；或用户在对话里说「弄好了」。你**下一回合读 `review/review_result.json` + `state.json`** 决定下一步；若该文件还没出现，说明用户还在操作，继续等待即可。
6. **页面打不开 / 报 `ERR_CONNECTION_REFUSED` 时排查**：`lsof -nP -iTCP:<端口> -sTCP:LISTEN` 看是否在监听；不在就按本协议**重新分离启动**（用同一 `--port` 让已打开的页面恢复）。
- **左侧分类侧边栏 + 右侧卡片**：角色三视图 / 场景 / 分镜机位 / 视频片段 / 语音配音；侧边栏底部「打开工作目录」「设置（配置）」。
- **深链直达**：应用支持 URL hash 路由。需要用户去某处时，给带锚点的链接即可：
  `…/#config`（配置 + API Key）、`…/#characters`、`…/#scenes`、`…/#shots`、`…/#clips`、`…/#voices`。
- **边生成边看进度（并行）**：把要生成的资产写成 `plan.json` 交给 `--plan`，应用**立刻打开**、后台 worker 池**并行**生成（默认 4 路，`--concurrency` 可调）。
  每个资产即时是一张占位卡片，带状态（排队 / 生成中% / 完成 / 失败）+ 顶部总进度。你这轮回复很快结束，不再长时间「思考中」阻塞。
  `plan.json` 形如（字段对应 `gen_*.py` 参数）：
  ```json
  {"tasks":[
    {"category":"characters","id":"char_01","name":"林夏","prompt":"...","gender":"女","views":"front,side,back","sample":true},
    {"category":"scenes","id":"scene_01","name":"便利店","prompt":"..."},
    {"category":"shots","id":"shot_01","prompt":"...","characters":"char_01","scene":"scene_01"},
    {"category":"clips","id":"clip_01","prompt":"...","first_frame":"assets/shots/shot_01.png","resolution":"480p","duration":5,"sample":true}
  ]}
  ```
- **用户在应用里**：看进度；完成的卡片逐项「通过/需修改」+ 意见，或改提示词/参考图/模型/设置后「重新生成」；
  失败的点「重试」（沿用原始计划参数）；侧边栏「设置」随时改全局配置/Key（即时落盘生效）；「全部停止」取消排队。
- **提交闭环**：用户点头部「继续」或「重做这一批」→ 应用写 `review/review_result.json` 并自行退出。
  你**下一回合读 `review/review_result.json`**（每项 `decision`/`note`/`status`、`action`、各任务最终状态）+ `state.json` 决定下一步；没出现就是用户还在操作。
  `通过`→`approved`、`需修改`→`draft`；用户在应用里重生成过的项 state.json 已是最新。
- **回复要短**：对话里 1–3 句引导即可（"已打开应用/已开始生成，请在页面里…"），主体在应用。不要在对话里长篇罗列分镜/规格。

## 工作流总览

```
阶段0 启动应用 ──→ 阶段1 对齐+生成角色/场景/分镜(应用内看进度审核) ──→ 阶段2 生成模式 ──→ 阶段3 样片/成片(应用内)
  建目录·开应用·配Key   ▲  角色三视图·音色·场景·故事·机位            低配样片→确认→成片
  (模型/参数应用内改)     │  (可反复确认, 接收用户参考素材)                      │
                       └──────────────────── 修改 / 续集循环 ◄────────────────┘
```

## 阶段 0：建目录 + 开应用 + 配 Key（硬性第一步）

用户第一次提出做短剧/视频时，**你就把工作目录建好、把应用启动并打开**，不要在对话里长篇问规格。

1. **选定工作目录**（你来定，唯一要决定的根目录，如工作区下 `<workspace>/<英文短名>`）并初始化：
   ```bash
   python scripts/init_project.py --project /abs/path/<项目目录> --title "<标题>"
   ```
2. **按上面的「❗启动协议」分离常驻启动应用**（`nohup … & disown`；首次还没资产也能开）：
   ```bash
   nohup python3 scripts/serve_review.py --project /abs/path/<项目目录> --port 8765 > /abs/path/<项目目录>/review/serve.log 2>&1 & disown
   sleep 1; cat /abs/path/<项目目录>/review/serve_url.txt   # 取真实 URL
   ```
   把读到的**真实链接**放进回复：「已为你打开创作台 [打开 ↗](http://127.0.0.1:<实际端口>/#config)。请在『设置』里填 API Key，填好我就开始生成。」
3. **配 Key**：用户在应用 `#config` 区填 API Key → 保存即写 `.sa_key`、即时生效。
   （若工作区已注入环境变量 `SENSEAUDIO_API_KEY`，则无需填，应用会显示「已配置」。）
4. Key 就绪后进入阶段 1。**之后一切都在这个工作目录 + 这个应用里**；改模型/参数在应用「设置」里随时进行。

> Key 来源优先级：环境变量 `SENSEAUDIO_API_KEY` > 项目 `.sa_key`。生成前可 `check_key.py`（退出码 2 = 缺 Key → 引导用户去 `#config`）。
> 不确定接口细节查 [references/senseaudio-api.md](references/senseaudio-api.md)。`selftest.py` 是开发者离线自检（内部用 `--mock`），与正式产出无关。

## 脚本速查

| 任务 | 命令 |
|------|------|
| **初始化项目** | `python scripts/init_project.py --project ./drama --title "..."`（建固定目录结构 + state.json） |
| **启动唯一前端(实时应用)** | `nohup python3 scripts/serve_review.py --project ./drama --port 8765 [--plan …] [--concurrency 4] > ./drama/review/serve.log 2>&1 & disown`（**分离常驻，不要前台、不要 run_in_background**）→ `cat ./drama/review/serve_url.txt` 取真实 URL 放进回复；可深链 `…/#config`/`#characters`/`#clips` |
| 保存 Key（一般由应用 `#config` 完成） | `python scripts/save_key.py --project ./drama --key "<api_key>"` |
| 生成前检查 Key | `python scripts/check_key.py --project ./drama`（退出码 2 = 缺 Key，引导用户去 `#config`） |
| 应用配置预设(可选/调试) | `python scripts/apply_config.py --project ./drama --config ./preset.json`（一般用户在应用「设置」里改，无需此命令） |
| 角色三视图（一张设定图） | `python scripts/gen_image.py --project ./drama --type character --id char_01 --name 林夏 --prompt "..." --ratio 16:9` |
| 角色分张参考图 | `… --type character --id char_01 --prompt "..." --views front,side,back` |
| 场景图 | `… --type scene --id scene_01 --name 便利店 --prompt "..."` |
| 分镜机位图 | `… --type shot --id shot_01 --prompt "..." --reference assets/characters/char_01_front.png` |
| 列出音色 | `python scripts/gen_voice.py --list` |
| 合成台词语音 | `python scripts/gen_voice.py --project ./drama --character char_01 --voice-id female_0033_b --text "..."` |
| 视频抽帧（承接/续接） | `python scripts/extract_frames.py --video prev.mp4 --out ./drama/assets/refs --which last` |
| 生成样片（480p 最省） | `python scripts/gen_video.py --project ./drama --id clip_01 --sample --prompt "..." --first-frame assets/shots/shot_01.png --duration 5` |
| 生成成片 | `python scripts/gen_video.py --project ./drama --id clip_01 --resolution 1080p --prompt "..." --first-frame ... --duration 8` |
| 成本预估 | `python scripts/estimate_cost.py --project ./drama` |

> 注：图/音/视频一般**不用你手敲命令逐个跑**——写进 `plan.json` 交给 `serve_review.py --plan`，让应用并行生成并显示进度；
> 上面的 `gen_*.py` 命令是这些任务底层调用的脚本（应用「重新生成」也走它们），单独调试时才直接用。

在 skill 目录下运行，或用完整路径。生成草稿优先加 `--sample`（图）/`--sample`（视频→480p）省积分。

## 项目结构（固定，用户只需决定根目录）

**用户唯一要决定的是「工作目录」(根目录)；其下所有路径都已固定**，由 `project_utils.SUBDIRS` 单一定义，
`init_project.py` 据此创建。生成脚本与实时应用都从这里取目录，落盘位置可预期、无需用户选择：
```
<根目录>/                    # 用户决定的唯一路径（work_dir）
├── state.json              # 唯一状态源：含 config（配置）、各资产；见 templates/state-schema.md
├── .sa_key                 # API Key（用户在应用 #config 填，不进 git、不展示）
├── assets/
│   ├── characters/         # 人设图（角色三视图 / 设定图）
│   ├── scenes/             # 场景图
│   ├── shots/              # 分镜图（机位预览）
│   ├── voices/             # 语音参考（配音 / 声音素材）
│   └── refs/               # 参考素材（用户上传 / 抽帧）
├── output/                 # 成片输出（生成的视频）
├── review/                 # 实时应用产物：plan.json（生成计划）、serve_url.txt（应用链接）、review_result.json（提交结果）
└── docs/                   # 剧本 / 说明
```
> 改动目录结构只需改 `project_utils.SUBDIRS` 一处；需要某类目录的绝对路径用 `pu.subdir(project, "shots")`。
> 配置不落单独文件，统一存在 `state.json` 的 `config` 字段（用户在应用「设置」里改 → `/api/config` 落盘）。

**应用内置目录入口**：实时应用侧边栏底部有「打开工作目录」，可在文件管理器/浏览器里展开看真实文件；
页内每张图片都支持**点击放大预览**与**下载**（参考图缩略图同样可点击预览）。

---

## 阶段 1：对齐需求

**目标：** 把用户的构想落成可执行规格——登场人物（含三视图与音色）、场景、故事、机位。

**步骤：**
1. 用 [templates/brief.md](templates/brief.md) 逐项对齐：题材、画幅、风格、人物、场景、故事、机位。缺口处提问，**可多轮反复确认**。
2. 接收用户参考素材：图像/视频/音频存到 `assets/refs/`，图像作参考图，视频用 `extract_frames.py` 抽帧。
3. **把要生成的资产写成 `plan.json`**（角色三视图 / 场景 / 分镜 / 必要的配音），各任务字段对应 `gen_*.py` 参数：
   - **锁性别**：角色任务带 `"gender":"男/女"`，防止性别漂移；草稿阶段带 `"sample":true` 省积分。
   - **统一画风**：先做一个角色当基准，其余角色用 `"style_ref":"<基准角色id>"` 参考它出同款画风。详见 [references/prompting-guide.md](references/prompting-guide.md)。
   - **分镜**带 `"characters":"char_01,char_02"`（自动注入角色身份锚点+参考图，防角色消失/串戏）、`"scene":"scene_01"`。
4. **按「❗启动协议」分离常驻启动应用**（先开页面再边生成边看进度）：
   ```bash
   nohup python3 scripts/serve_review.py --project ./drama --port 8765 --plan ./drama/review/plan.json > ./drama/review/serve.log 2>&1 & disown
   sleep 1; cat ./drama/review/serve_url.txt
   ```
   把读到的真实链接放进回复，说明：页面会并行生成、卡片显示进度；完成后切分类逐项「通过/需修改」填意见，
   不满意可直接改提示词/参考图/模型/设置后「重新生成」，失败的点「重试」，确认无误点头部「继续」。
   用户点「继续/重做这一批」后应用写 `review/review_result.json` 并退出；你下一回合读它 + `state.json` 续行。
   （也可不用 plan、先自己跑少量 `gen_*.py` 再纯审核——但**多张资产优先用 plan 让用户看进度**。）

**门禁：** 页面已把 `通过` 的资产置 `approved`、`需修改` 的置回 `draft`（用户也可能已在页面内重生成）。读结果后只对仍未通过的项继续处理。

**退出：** 角色、场景、（必要的）音色、分镜均确认 → `phase: "mode"`。

---

## 阶段 2：确定生成模式

**目标：** 明确每个视频片段「从什么生成」。详见 [references/generation-modes.md](references/generation-modes.md)。

和用户确认本段属于哪种：
- **纯文生** / **首帧** / **尾帧** / **首尾帧** / **参考图驱动**
- **承接前置视频**：给已托管视频 URL（`--prev-video`），或抽前段末帧作 `--first-frame`。
- **续接后置视频**：给 `--next-video`，或抽后段首帧作 `--last-frame`。
- **首尾衔接两段**：前段末帧作首帧 + 后段首帧作尾帧，生成中间过渡。

把每个片段的模式与输入记到 `state.clips[]`（`gen_video.py` 会自动判定并写入 `mode`）。

**退出：** 模式与输入确定 → `phase: "generate"`。

---

## 阶段 3：样片 → 成片

**目标：** 先低配样片验证，再出成片，避免浪费积分。

1. **先问用户**：先出低配样片确认效果，还是需求已很清楚直接出成片？给出成本对比：
   ```bash
   python scripts/estimate_cost.py --video-res 480p --video-seconds 5
   python scripts/estimate_cost.py --video-res 1080p --video-seconds 8
   ```
2. **样片**（最省：480p）：把片段写成 `plan.json` 的 `clips` 任务（带 `"sample":true`、首/尾帧、参考、时长），
   启动实时审核服务，让用户**边生成边看进度**：
   ```bash
   nohup python3 scripts/serve_review.py --project ./drama --port 8765 --plan ./drama/review/plan.json > ./drama/review/serve.log 2>&1 & disown   # 分离常驻；随后 cat review/serve_url.txt 取真实 URL
   ```
   用户在「视频片段」分类里看进度与样片；不满意可直接改提示词/模型/分辨率/时长后「重新生成」，或在「设置」里调全局再重生成。
3. **成片**（用户确认后升画质）：用户可直接在页面卡片里把分辨率调到 720p/1080p、关掉「样片」勾选后「重新生成」；
   或你新写一份成片 `plan.json` 再起服务。沿用同样的首/尾帧与参考图。

**默认值：** 样片 480p / 5s；成片 720p 起步，1080p 用于定稿镜头。竖屏短剧 `ratio=9:16`。

---

## 修改 / 续集循环

大多数修改用户**直接在应用里完成**：改某卡片的提示词/参考图/模型/设置后「重新生成」即可，无需你介入。
读 `review/review_result.json`：逐 `items` 看 `decision`/`note`，只重做仍 `需修改` 的项，其余保持 `approved`。

| 用户诉求 | 回到 | 操作 |
|----------|------|------|
| 性别错 / 衣服对不上 / 角色消失或重复 | 阶段1 | 重做该项：角色带 `gender`、新角色 `style_ref` 对齐画风；分镜/视频带 `characters`（注入锚点+各角色参考图），prompt 写清"画面共 N 人、谁在做什么" |
| 改角色/场景/分镜外观 | 阶段1 | 用户在卡片上改提示词/参考图后「重新生成」；或你改 plan 重生成该项 |
| 换生成方式（如改用首尾帧） | 阶段2 | 调整该 clip 的输入参数 |
| 画质/时长不满意 | 阶段3 | 升/调参数重出 |
| 续写下一段剧情 | 阶段1→3 | 新增分镜/clip，用前段末帧链式衔接（见 generation-modes.md） |

## 硬性规则

| 规则 | 说明 |
|------|------|
| 唯一前端是实时应用 | 所有配置/生成/审核都在 `serve_review.py`（**`nohup … & disown` 分离常驻**，不要前台、不要 run_in_background；读 `serve_url.txt` 取真实端口给可点击链接）；会话开始即启动。用户提交后读 `review/review_result.json` 再继续。不要再生成任何静态确认页/配置页 |
| 场景图=空镜 | 场景图只画环境，prompt 不要写人物动作（`gen_image` 对 scene 已强制追加「无人物」约束作兜底）；人物留给分镜 |
| 样片先于成片 | 除非用户明确说需求已清楚、直接出成片 |
| 只改受影响项 | 修订时不要重生成已 `approved` 的资产 |
| Key 不落盘 | API Key 只用环境变量，不写进 state.json / 不提交 git |
| 一致性优先 | 跨镜复用角色图作参考、用首尾帧链式约束 |

## 延伸阅读
- [references/senseaudio-api.md](references/senseaudio-api.md) — 接口、模型、价格、size 取值
- [references/generation-modes.md](references/generation-modes.md) — 阶段2 各模式与参数
- [references/prompting-guide.md](references/prompting-guide.md) — 提示词与一致性
- [templates/state-schema.md](templates/state-schema.md) — state.json 字段
- [templates/brief.md](templates/brief.md) — 阶段1 对齐清单
