---
name: video-creator
description: >-
  帮助用户用 SenseAudio API 创作 AI 短剧视频。三阶段流水：①人设+场景 → ②分镜（参考人设/场景图）
  → ③视频成片（参考分镜图生成，先 480p 样片再升成片）。全程在一个本地实时 Web 应用里看进度与审核。
  适用于 AI 短剧、AI 视频生成、分镜、角色设计、视频续写/续接等场景。
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
5. **页面打不开 / 报 `ERR_CONNECTION_REFUSED` 时排查**：`lsof -nP -iTCP:<端口> -sTCP:LISTEN` 看是否在监听；不在就按本协议**重新分离启动**（用同一 `--port` 让已打开的页面恢复）。

### 三阶段流水（核心！分镜/视频必须在人设/场景之后生成）
应用把工作分成**三个阶段**，并在生成队列里**按阶段门控**（上一阶段全部结束前，绝不启动下一阶段）：
- **阶段1 设定**：`characters`（人设）+ `scenes`（场景）——彼此独立，并行出。
- **阶段2 分镜**：`shots`——**用阶段1 的人设图+场景图作参考**（带 `characters`/`scene` 字段，脚本自动把对应图注入为参考图，无需手动上传）。
- **阶段3 成片**：`clips`（视频）+ `voices`（配音）——视频带 `characters`（自动注入各角色设定图）+ 分镜帧。

> **分镜/视频的参考图由服务自动解析、不会再「忘记」**：生成前服务从已完成的阶段1 结果取对应人设图/场景图作参考（写进任务、卡片可见）。
> 你仍应给分镜/视频任务写上 `characters`(+`scene`)——决定身份锚点作用在谁身上（防漂移）；完全没写时服务才退化为「用全体角色设定图」兜底。
> **多角色+场景的分镜**：图像 API 只收一张参考图，`gen_image` 会自动把「各角色设定图 + 场景图」用 Pillow **拼成一张参考拼贴**喂进去（无 Pillow 时回退单图）——模型能同时看到所有角色与场景。视频阶段原生支持多参考图。
> **身高/体型比例（强一致性关键）**：给角色任务加 `"build"`（如 `"娇小，比男主矮一头"`/`"高挑"`）；**并且在每条分镜、视频的提示词里都显式写明比例关系**——人物之间（如「男主比女主高约一头」）、人物与场景/道具（如「女主头顶约到门框三分之二」「小凳子约到女主膝盖」）。别只靠锚点，提示词里写清楚才能跨镜稳定，避免人物忽大忽小、与场景比例失真。
> 你也不必把所有阶段一次性塞进一个 plan——**推荐分阶段推进**：先出阶段1，用户在应用里看/调，确认方向后再续作阶段2（见下「阶段推进」）。

### ❗职责分工：AI 只「准备」，用户在 UI 触发生成
- **你（AI）只负责把生成配置准备好**（写提示词/参考图/模型/设置成 plan 任务）并打开/推进应用。**不替用户执行生成。**
- `--plan` 和 `POST /api/plan` 都只把任务**备为「待生成」草稿**（不自动跑）；**用户在 UI 点「▶ 开始生成」（或某卡片的「▶ 生成」）才真正生成**。
- 别在对话里说"我已开始生成/已生成完"——你做的是准备好任务、把 UI 给用户。

### 如何推进阶段 / 续作（应用是常驻看板）
- **❗用户说「继续」时，先查"做到哪一步了"**：跑 `python scripts/status.py --project "$P"`（直接读 stdout，**不要用 curl|python 管道**——易出错）。
  它读 **`state.json`（事实来源）**，列出各阶段已生成/已通过的资产，并给出 `next_stage`。
  > 关键：**判断已完成看 `state.json` 的资产，不要看实时服务的任务队列**——服务重启后内存队列会清空（显示 0 任务），但已生成的资产仍在 state.json。
- 据 status 结果**只准备缺失的 / `next_stage` 的任务**：`POST /api/plan {"tasks":[…]}`（备为草稿）。
  **绝不重推已生成/已通过的资产**（否则会把用户做好的阶段又变回待生成、全部重来）。`需修改` 的项才重做。
- 用户点「开始生成」只跑**当前阶段**（按阶段门控）；改卡片后「重新生成」、草稿「生成」、失败「重试」都由用户自助。
- 没有 `review_result.json` 提交闭环；服务**常驻**直到用户点「关闭服务」或你 `--stop`。

### 如何停止服务（`--daemon` 是常驻的，关闭对话不会自动停——这是有意的，避免生成中被杀）
- **用户在应用里点侧边栏「⏻ 关闭服务」**（无终端也能停；成果都在工作目录里，不会丢）。
- **用户在对话里说「关掉服务」** → 你运行：`python3 scripts/serve_review.py --project <工作目录> --stop`（读 `review/serve.pid` 结束进程并清理）。
- 兜底（手动）：`kill $(cat <工作目录>/review/serve.pid)`，或 `lsof -ti :<端口> | xargs kill`。
> 启动新项目前，先 `--stop` 掉旧项目的服务，避免多个服务堆叠占端口。

- **左侧分类侧边栏（按三阶段分组）+ 右侧卡片**：阶段1 角色三视图/场景、阶段2 分镜机位、阶段3 视频片段/语音配音；侧边栏底部「打开工作目录」「设置（配置）」「关闭服务」。
- **深链直达**：应用支持 URL hash 路由。需要用户去某处时给带锚点的链接：`…/#config`（配置 + API Key）、`…/#characters`、`…/#scenes`、`…/#shots`、`…/#clips`、`…/#voices`。
- **准备 → 用户触发 → 并行生成（阶段门控）**：把资产写成 `plan.json` 交给 `--plan`（或运行中 `POST /api/plan`）→ 出现「待生成」草稿卡片 → 用户点「开始生成」→ worker 池**并行**跑（默认 4 路）；每个资产带状态（待生成/排队/生成中%/完成/失败）+ 顶部总进度。
  参考图字段写 **`references`（数组）**；`reference`（单数字符串）也会被自动归一，但**统一用 `references`** 更稳。卡片支持 **Ctrl+V 粘贴**、「📁 工作目录」选图、上传。
  `plan.json` 形如（字段对应 `gen_*.py` 参数；**角色默认出一张三视图合图，不要用 `views` 分张——分张是 3 倍价钱**）：
  ```json
  {"tasks":[
    {"category":"characters","id":"char_01","name":"林夏","prompt":"…身份锚点+外观+体型…","gender":"女","build":"娇小，比男主矮一头"},
    {"category":"scenes","id":"scene_01","name":"便利店","prompt":"…只写环境，无人物…"},
    {"category":"shots","id":"shot_01","prompt":"中景，两人在玄关对话；男主比女主高约一头，女主头顶约到门框三分之二","characters":"char_01,char_02","scene":"scene_01"},
    {"category":"clips","id":"clip_01","prompt":"…镜头动作+比例…","characters":"char_01,char_02","shots":"shot_01","resolution":"480p","duration":5,"sample":true}
  ]}
  ```
- **用户在应用里**：看进度；完成的卡片逐项「通过/需修改」+ 意见，或改提示词/参考图/模型/设置后「重新生成」；失败的点「重试」（沿用原始计划参数，含自动注入的参考图）；侧边栏「设置」随时改全局配置/Key；「全部停止」取消排队。审核结果（`review_decision`）直接写进 `state.json`，你读它即知用户认可了什么。
- **回复要短**：对话里 1–3 句引导即可（"已为你备好任务并打开应用，请在页面里点『开始生成』…"），主体在应用。不要在对话里长篇罗列分镜/规格。

## 工作流总览

```
阶段0 启动应用 ──→ 阶段1 对齐+生成角色/场景/分镜(应用内看进度审核) ──→ 阶段2 生成模式 ──→ 阶段3 样片/成片(应用内)
  建目录·开应用·配Key   ▲  角色三视图·音色·场景·故事·机位            低配样片→确认→成片
  (模型/参数应用内改)     │  (可反复确认, 接收用户参考素材)                      │
                       └──────────────────── 修改 / 续集循环 ◄────────────────┘
```

## 阶段 0：建目录 + 开应用 + 配 Key（硬性第一步）

用户第一次提出做短剧/视频时，**你就把工作目录建好、把应用启动并打开**，不要在对话里长篇问规格。

1. **为本轮对话新建隔离项目目录**：选一个固定的**总工作目录**（如 `<workspace>/sa_drama`），用 `--parent` 让脚本在其下**自动建一个带唯一 id 的子目录**作为本轮项目：
   ```bash
   python scripts/init_project.py --parent /abs/path/sa_drama --title "<标题>"
   # 输出末行 PROJECT:/abs/path/sa_drama/<标题>_<时间>_<随机> —— 记下这个绝对路径，本轮一切都用它（记为 $P）
   ```
   - **每轮对话都新建（不要复用旧目录）**：不同对话各自隔离，旧历史/资产不会串进来。
   - **本轮内复用**：同一对话的后续阶段都用同一个 `$P`，不要再新建。
2. **按上面的「❗启动协议」分离常驻启动应用**（`nohup … & disown`；首次还没资产也能开）：
   ```bash
   nohup python3 scripts/serve_review.py --project "$P" --port 8765 > "$P/review/serve.log" 2>&1 & disown
   sleep 1; cat "$P/review/serve_url.txt"   # 取真实 URL
   ```
   把读到的**真实链接**放进回复：「已为你打开创作台 [打开 ↗](http://127.0.0.1:<实际端口>/#config)。请在『设置』里填 API Key，然后在页面点『开始生成』。」
3. **配 Key**：用户在应用 `#config` 区填 API Key → 保存即写 `.sa_key`、即时生效。
   （若工作区已注入环境变量 `SENSEAUDIO_API_KEY`，则无需填，应用会显示「已配置」。）
4. Key 就绪后进入阶段 1。**本轮一切都在 `$P` 这个项目目录 + 这个应用里**；改模型/参数在应用「设置」里随时进行。

> Key 来源优先级：环境变量 `SENSEAUDIO_API_KEY` > 项目 `.sa_key`。生成前可 `check_key.py`（退出码 2 = 缺 Key → 引导用户去 `#config`）。
> 不确定接口细节查 [references/senseaudio-api.md](references/senseaudio-api.md)。`selftest.py` 是开发者离线自检（内部用 `--mock`），与正式产出无关。

## 脚本速查

| 任务 | 命令 |
|------|------|
| **初始化项目(每轮唯一)** | `python scripts/init_project.py --parent /abs/sa_drama --title "..."` → 在总目录下建唯一子目录、打印 `PROJECT:<路径>`（隔离不同对话）。也可 `--project <显式目录>` |
| **查项目进度(续作前必看)** | `python scripts/status.py --project "$P"` → 各阶段已完成/已通过资产 + `next_stage`（读 state.json，不依赖实时服务）；据此只补缺失/下一阶段 |
| **启动唯一前端(实时应用)** | `nohup python3 scripts/serve_review.py --project ./drama --port 8765 [--plan …] [--concurrency 4] > ./drama/review/serve.log 2>&1 & disown`（**分离常驻，不要前台、不要 run_in_background**）→ `cat ./drama/review/serve_url.txt` 取真实 URL 放进回复；可深链 `…/#config`/`#characters`/`#clips` |
| **停止服务** | `python3 scripts/serve_review.py --project ./drama --stop`（或用户在应用点「⏻ 关闭服务」）；启动新项目前先停旧的 |
| 保存 Key（一般由应用 `#config` 完成） | `python scripts/save_key.py --project ./drama --key "<api_key>"` |
| 生成前检查 Key | `python scripts/check_key.py --project ./drama`（退出码 2 = 缺 Key，引导用户去 `#config`） |
| 应用配置预设(可选/调试) | `python scripts/apply_config.py --project ./drama --config ./preset.json`（一般用户在应用「设置」里改，无需此命令） |
| 角色三视图（一张设定图，**默认这个**） | `python scripts/gen_image.py --project ./drama --type character --id char_01 --name 林夏 --prompt "..." --ratio 16:9` |
| 角色分张参考图（**慎用·3 倍价钱**） | `… --type character --id char_01 --prompt "..." --views front,side,back`（仅在用户明确要分张时） |
| 场景图 | `… --type scene --id scene_01 --name 便利店 --prompt "..."` |
| 分镜机位图 | `… --type shot --id shot_01 --prompt "..." --reference assets/characters/char_01_front.png` |
| 列出音色 | `python scripts/gen_voice.py --list` |
| 合成台词语音 | `python scripts/gen_voice.py --project ./drama --character char_01 --voice-id female_0033_b --text "..."` |
| 视频抽帧（承接/续接） | `python scripts/extract_frames.py --video prev.mp4 --out ./drama/assets/refs --which last` |
| 生成样片（480p 最省） | `python scripts/gen_video.py --project ./drama --id clip_01 --sample --prompt "..." --shots shot_01 --characters char_01 --duration 5`（参考分镜图+角色，不用首尾帧） |
| 生成成片 | `python scripts/gen_video.py --project ./drama --id clip_01 --resolution 1080p --prompt "..." --shots shot_01 --characters char_01 --duration 8` |
| 成本预估 | `python scripts/estimate_cost.py --project ./drama` |

> 注：图/音/视频一般**不用你手敲命令逐个跑**——写进 `plan.json` 交给 `serve_review.py --plan`，让应用并行生成并显示进度；
> 上面的 `gen_*.py` 命令是这些任务底层调用的脚本（应用「重新生成」也走它们），单独调试时才直接用。

在 skill 目录下运行，或用完整路径。生成草稿优先加 `--sample`（图）/`--sample`（视频→480p）省积分。

## 项目结构（总目录固定，每轮对话一个隔离子目录）

**用户只决定一个「总工作目录」；每轮对话由 `init_project --parent` 在其下新建一个带唯一 id 的项目子目录**（隔离不同对话，旧历史不串）。
子目录内的所有路径由 `project_utils.SUBDIRS` 单一定义、自动创建：
```
<总工作目录>/                  # 用户决定的唯一根（如 <workspace>/sa_drama）
└── <标题>_<时间>_<随机>/      # 每轮对话一个项目（init_project --parent 自动建，互相隔离）
├── state.json              # 唯一状态源：含 config（配置）、各资产；见 templates/state-schema.md
├── .sa_key                 # API Key（用户在应用 #config 填，不进 git、不展示）
├── assets/
│   ├── characters/         # 人设图（角色三视图 / 设定图）
│   ├── scenes/             # 场景图
│   ├── shots/              # 分镜图（机位预览）
│   ├── voices/             # 语音参考（配音 / 声音素材）
│   └── refs/               # 参考素材（用户上传 / 抽帧）
├── output/                 # 成片输出（生成的视频）
├── review/                 # 实时应用产物：plan.json（生成计划）、serve_url.txt（应用链接）、serve.pid、serve.log
└── docs/                   # 剧本 / 说明
```
> 改动目录结构只需改 `project_utils.SUBDIRS` 一处；需要某类目录的绝对路径用 `pu.subdir(project, "shots")`。
> 配置不落单独文件，统一存在 `state.json` 的 `config` 字段（用户在应用「设置」里改 → `/api/config` 落盘）。

**应用内置目录入口**：实时应用侧边栏底部有「打开工作目录」，可在文件管理器/浏览器里展开看真实文件；
页内每张图片都支持**点击放大预览**与**下载**（参考图缩略图同样可点击预览）。

---

## 阶段 1：对齐需求

**目标：** 把用户的构想落成可执行规格——登场人物（含三视图与音色）、场景、故事、机位。

**步骤（按三阶段流水推进；先只做阶段1）：**
1. 用 [templates/brief.md](templates/brief.md) 逐项对齐：题材、画幅、风格、人物、场景、故事、机位。缺口处提问，**可多轮反复确认**。
2. 接收用户参考素材：图像/视频/音频存到 `assets/refs/`，视频用 `extract_frames.py` 抽帧。
   **❗参考图必须对应到正确的角色，不能靠顺序猜**：用户一次给多张人物参考图时，先**逐张看图确认谁是谁**，
   再按角色落盘命名（如 `uploaded_<角色id>.png`，例 `uploaded_female.png`）并写进对应角色任务的参考；不确定就**问用户哪张对应哪个角色**。
   更稳的做法：让用户在应用里**对着该角色的卡片上传/「📁 工作目录」选图**（落到哪张卡片就是哪个角色，绝不串）。生成后核对卡片上的参考图与提示词是否同一人。
3. **先写阶段1 的 `plan.json`**——只放 `characters`（人设）+ `scenes`（场景），各任务字段对应 `gen_*.py` 参数：
   - **角色出一张三视图合图**：不要带 `views`（分张 = 3 倍价钱）；带 `"gender":"男/女"` 锁性别、`"build"` 写身高/体型（防跨镜比例漂移）；草稿带 `"sample":true` 省积分。
   - **统一画风**：先做一个角色当基准，其余角色 `"style_ref":"<基准角色id>"` 出同款画风。详见 [references/prompting-guide.md](references/prompting-guide.md)。
   - **场景只写环境、无人物**（脚本对 scene 已强制追加「无人物」兜底）。
4. **按「❗启动协议」分离常驻启动应用**（把 plan 作为「待生成」备好，开页面让用户触发）：
   ```bash
   nohup python3 scripts/serve_review.py --project ./drama --port 8765 --plan ./drama/review/plan.json > ./drama/review/serve.log 2>&1 & disown
   sleep 1; cat ./drama/review/serve_url.txt
   ```
   把真实链接放进回复，说明：页面已列出「待生成」任务，**点「开始生成」**即按阶段并行跑、卡片显示进度；可逐项「通过/需修改」，不满意改了「重新生成」，失败点「重试」。
5. **续作阶段2/3**：用户认可阶段1（或说「继续」）后，先 `python scripts/status.py --project "$P"` 看 `next_stage` 与已完成资产，
   只为缺失/下一阶段写任务：阶段2（`shots`，带 `characters`/`scene`）→ `POST /api/plan` 备草稿；阶段2 认可后再推阶段3（`clips` 带 `shots`/`characters`、`voices`）。
   **不要重推已完成的阶段**。队列按阶段门控，分镜/视频自动拿前序的人设/场景图作参考。

**门禁：** 页面把 `通过` 的资产标 `approved`、`需修改` 标 `draft`（直接写进 `state.json`）。续作前用 `status.py` 看完成情况，只对未通过/缺失的项处理。

**退出：** 阶段1（角色+场景）确认后即可推进阶段2（分镜）；分镜确认后推进阶段3。

---

## 阶段 2：分镜（确认机位后转视频）

**目标：** 把故事拆成一组**分镜机位图**（每个镜头一张）。分镜自动参考阶段1 的人设图+场景图，并在 prompt 里写清景别/机位/动作/**比例**。
分镜确认后，进入阶段3——**视频以分镜图作参考生成**（不用首/尾帧）。详见 [references/generation-modes.md](references/generation-modes.md)。

**退出：** 分镜确认 → 进入阶段3。

---

## 阶段 3：样片 → 成片

**目标：** 先低配样片验证，再出成片，避免浪费积分。

1. **先问用户**：先出低配样片确认效果，还是需求已很清楚直接出成片？给出成本对比：
   ```bash
   python scripts/estimate_cost.py --video-res 480p --video-seconds 5
   python scripts/estimate_cost.py --video-res 1080p --video-seconds 8
   ```
2. **样片**（最省：480p）：服务通常已在阶段1 起好——把 `clips` 任务（带 `"sample":true`、`shots`(分镜id，作参考)、`characters`、`duration`）
   `POST <url>/api/plan` 备为草稿，用户在「视频片段」分类点「开始生成」后**边生成边看进度**。（若服务没在跑，按启动协议起一份。）
   ```bash
   curl -s http://127.0.0.1:<端口>/api/plan -d '{"tasks":[{"category":"clips","id":"clip_01","prompt":"…镜头动作+比例…","characters":"char_01","shots":"shot_01","resolution":"480p","duration":5,"sample":true}]}'
   ```
3. **成片**（用户确认后升画质）：用户可直接在页面卡片里把分辨率调到 720p/1080p、关掉「样片」勾选后「重新生成」；或你 `POST /api/plan` 推一份成片任务。沿用同样的分镜图与角色参考。

**默认值：** 样片 480p / 5s；成片 720p 起步，1080p 用于定稿镜头。竖屏短剧 `ratio=9:16`。

---

## 修改 / 续集循环

大多数修改用户**直接在应用里完成**：改某卡片的提示词/参考图/模型/设置后「重新生成」即可，无需你介入。
当用户让你帮忙时，先 `python scripts/status.py --project "$P"` 看各项 `review`/完成情况，只重做仍 `需修改`/缺失的项。

| 用户诉求 | 回到 | 操作 |
|----------|------|------|
| 性别错 / 衣服对不上 / 角色消失或重复 | 阶段1 | 重做该项：角色带 `gender`、新角色 `style_ref` 对齐画风；分镜/视频带 `characters`（注入锚点+各角色参考图），prompt 写清"画面共 N 人、谁在做什么" |
| 改角色/场景/分镜外观 | 阶段1 | 用户在卡片上改提示词/参考图后「重新生成」；或你改 plan 重生成该项 |
| 镜头内容/构图不对 | 阶段2 | 改分镜图（它是视频的参考），再重出该 clip |
| 画质/时长不满意 | 阶段3 | 升/调参数重出 |
| 续写下一段剧情 | 阶段1→3 | 新增分镜→新 clip（参考新分镜图）；需承接旧片用 `--prev-video` 已托管 URL（见 generation-modes.md） |

## 硬性规则

| 规则 | 说明 |
|------|------|
| 唯一前端是实时应用 | 所有配置/生成/审核都在 `serve_review.py`（**`nohup … & disown` 分离常驻**，不要前台、不要 run_in_background；读 `serve_url.txt` 取真实端口给可点击链接）；会话开始即启动、常驻。不要再生成任何静态确认页/配置页 |
| 续作先查状态 | 续作前必跑 `status.py --project "$P"`（读 state.json，事实来源）确认各阶段已完成的资产；**只准备缺失/下一阶段，绝不重推已生成/已通过的项**（不要看实时服务的空任务队列就重来） |
| 三阶段顺序 | 必须 人设+场景(阶段1) → 分镜(阶段2) → 视频+语音(阶段3)；分镜/视频任务必带 `characters`(+`scene`)，参考图自动注入。队列已按阶段门控，但**你也应分阶段推进**让用户逐段确认 |
| 角色出一张三视图合图 | 角色任务**不要带 `views`**（分张 = 3 倍价钱）；默认单张三视图合图即可 |
| 场景图=空镜 | 场景图只画环境，prompt 不要写人物动作（`gen_image` 对 scene 已强制追加「无人物」约束作兜底）；人物留给分镜 |
| 样片先于成片 | 除非用户明确说需求已清楚、直接出成片 |
| 只改受影响项 | 修订时不要重生成已 `approved` 的资产 |
| Key 不落盘 | API Key 只用环境变量，不写进 state.json / 不提交 git |
| 视频=参考分镜图 | 视频以**分镜图（+角色设定图）作参考**生成，**不用首/尾帧**（首尾帧与参考素材不能混用，会 400）；clip 任务用 `shots` 指定参考的分镜 |
| 一致性优先 | 跨镜复用角色图/分镜图作参考；同组人物用同一套比例措辞 |
| 多主体参考 & 比例 | 多角色+场景的分镜：`gen_image` 自动拼「参考拼贴」（需 Pillow）让模型看到所有角色+场景；角色带 `build`；**分镜/视频提示词里必须显式写明人物之间、人物与场景/道具的大小比例**（如「男主比女主高一头」「女主头顶到门框三分之二」），跨镜保持一致 |
| 参考图对人不对位置 | 多张人物参考图必须**逐张看图**对应到正确角色（别按顺序猜），命名 `uploaded_<角色id>`；不确定就问用户。最稳：让用户在对应角色卡片上传/「📁 工作目录」选图。生成后核对参考图与提示词是否同一人 |

## 延伸阅读
- [references/senseaudio-api.md](references/senseaudio-api.md) — 接口、模型、价格、size 取值
- [references/generation-modes.md](references/generation-modes.md) — 阶段2 各模式与参数
- [references/prompting-guide.md](references/prompting-guide.md) — 提示词与一致性
- [templates/state-schema.md](templates/state-schema.md) — state.json 字段
- [templates/brief.md](templates/brief.md) — 阶段1 对齐清单
