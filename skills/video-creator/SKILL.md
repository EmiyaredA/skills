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

用 SenseAudio 的图像 / 视频 API 创作 AI 短剧。**整套交互只有一个前端：`serve_review.py` 这个本地实时 Web 应用。**
会话一开始就把它启动并打开，它就是用户从头到尾用的界面；**对话框只作为指挥/沟通渠道**，所有配置、生成、查看、确认都在 Web 应用里完成。

本 skill 运行在 SoWork/audioclaw 工作区、跑在用户本机。用户**没有终端**，所有脚本由**你（助手）**调用。

## 何时使用

用户提到 AI 短剧、AI 视频、视频生成、分镜、角色设计、视频续写/续接，或想分步预览确认后再生成视频。

## 三条最高优先级规则

1. **没有 Key 就让用户在应用里填，绝不 mock。** 真实生成前必须已配置 Key（环境变量 `SENSEAUDIO_API_KEY` 或项目 `.sa_key`）。
   没 Key 时唯一正确动作：把用户引导到应用配置区 `…/#config` 填入 Key（保存即写 `.sa_key`、即时生效）。
   严禁用 `--mock` 顶替或把占位文件当作品交付——`--mock` 只属于 `selftest.py` 离线自检。没 Key 时应用里的生成任务会直接标「失败」并提示去 `#config`。

2. **你只「准备」，用户在 UI 触发生成。** 你把提示词/参考图/模型写成 plan 任务（`--plan` 或 `POST /api/plan`），它们只是「待生成」草稿；
   **用户在 UI 点「▶ 开始生成」才真正跑**。别在对话里说"我已生成完"——你做的是备好任务、把 UI 交给用户。

3. **阶段顺序不可逆。** 人设+场景(阶段1) → 分镜(阶段2) → 视频成片(阶段3) → 导出(阶段4)。队列按阶段门控（上一阶段全部结束前不启动下一阶段），
   你也应**分阶段推进**让用户逐段确认，不要一次塞满三阶段。

## ❗启动协议（务必照做，否则页面打不开 / 会话卡死 / 服务被回收）

1. 先 `init_project.py` 建好工作目录。
2. **加 `--daemon` 常驻启动**——脚本自行双 fork 脱离会话，启动命令瞬间返回、进程独立存活、不随本回合/会话结束被回收（输出自动写进 `review/serve.log`，无需手动重定向）：
   ```bash
   python3 scripts/serve_review.py --project <工作目录> --port 8765 --daemon [--plan <工作目录>/review/plan.json]
   ```
   - **必须带 `--daemon`**：不带它会前台 `serve_forever` 不返回 → 本回合永久卡在「思考中」。
   - **不要用 `run_in_background`**：本工作区可能在回合/会话结束时回收它，导致页面突然 `ERR_CONNECTION_REFUSED`。`--daemon` 自行脱离会话才能一直活着。
3. **读取真实 URL——不要假设是 8765**！8765 常被占用，服务会自增端口（8766…）。启动后：
   ```bash
   sleep 1; cat <工作目录>/review/serve_url.txt   # → http://127.0.0.1:<实际端口>/
   ```
4. 把这个**真实链接**作为可点击链接放进回复（例：`[打开创作台 ↗](http://127.0.0.1:8766/#config)`），然后结束本回合，不阻塞等待。
5. **页面打不开 / `ERR_CONNECTION_REFUSED` 时**：`lsof -nP -iTCP:<端口> -sTCP:LISTEN` 看是否在监听；不在就**用同一 `--port` 重新 `--daemon` 启动**（让已打开的页面恢复）。

> **回复要短**：对话里 1–3 句引导即可（"已为你备好任务并打开应用，请在页面里点『开始生成』…"），主体在应用里。不要在对话里长篇罗列分镜/规格。

## 应用是什么样、怎么用

- **左侧按阶段分组的侧边栏 + 右侧卡片**：阶段1 角色三视图/场景、阶段2 分镜机位、阶段3 视频片段、阶段4 成片导出；侧边栏底部「设置（配置/Key）」「⏻ 关闭服务」。
- **深链直达**：URL hash 路由，需要用户去某处时给带锚点的链接：`…/#config`、`…/#characters`、`…/#scenes`、`…/#shots`、`…/#clips`、`…/#exports`。
- **生成流程**：你把任务写进 plan → 出现「待生成」草稿卡片 → 用户点「开始生成」→ worker 池**并行**跑（默认 4 路，按阶段门控）→ 每张卡片显示状态（待生成/排队/生成中%/完成/失败）+ 顶部总进度。
- **用户自助**：完成的卡片可逐项「通过/需修改」+ 意见，或改提示词/参考图/模型/设置后「重新生成」；失败的「重试」（沿用原始参数与自动注入的参考图）；「全部停止」取消排队。
  审核结果（`review_decision`）直接写进 `state.json`，你读它即知用户认可了什么。卡片支持 Ctrl+V 粘贴、「📁 工作目录」选图、上传；每张图可点击放大/下载，✕ 删除参考图。

## 三阶段流水的关键约定

- **阶段1 设定**：`characters`（人设）+ `scenes`（场景），彼此独立、并行出。
- **阶段2 分镜**：`shots`，用阶段1 的人设图+场景图作参考（任务带 `characters`/`scene`，服务自动注入对应图）。
- **阶段3 成片**：`clips`（视频，带 `shots` 分镜帧 + `characters` 角色图）。
- **阶段4 导出**：`exports`（把片段按剧情顺序拼成整片，见「阶段 4：导出成片」）。

> **参考图自动解析、不会「忘记」**：生成前服务从已完成的阶段1/2 结果取对应人设图/场景图/分镜图作参考（写进任务、卡片可见）。
> 你仍应给分镜/视频任务写 `characters`(+`scene`)——它决定身份锚点作用在谁身上（防漂移）；完全没写时才退化为「用全体角色图」兜底。
> **多角色+场景的分镜**：图像 API 只收一张参考图，`gen_image` 会用 Pillow 把「各角色图 + 场景图」**拼成一张参考拼贴**喂进去（无 Pillow 时回退单图）；视频阶段原生支持多参考图。
> **身高/体型比例（强一致性关键）**：给角色任务加 `build`（如「娇小，比男主矮一头」「高挑」），**并且在每条分镜、视频提示词里都显式写明比例关系**——人物之间（「男主比女主高约一头」）、人物与场景/道具（「女主头顶约到门框三分之二」）。只靠锚点不够，提示词写清才能跨镜稳定。

## 续作 / 推进阶段（应用是常驻看板）

- **用户说「继续」时，先查"做到哪一步了"**：跑 `python scripts/status.py --project "$P"`（直接读 stdout，不要用 curl|python 管道）。
  它读 **`state.json`（事实来源）**列出各阶段已生成/已通过的资产并给出 `next_stage`。
  > 判断已完成**看 state.json 的资产，不要看实时服务的任务队列**——服务重启后内存队列会清空（显示 0 任务），但已生成资产仍在 state.json。
- 据 status 结果**只准备缺失的 / `next_stage` 的任务**（`POST /api/plan {"tasks":[…]}` 备为草稿）。
  **绝不重推已生成/已通过的资产**（否则会把用户做好的阶段又变回待生成、全部重来）；只对 `需修改` 的项重做。

## 如何停止服务

服务靠 `--daemon` 常驻；关闭对话不会自动停（有意为之，避免生成中被杀）。
- 用户在应用点侧边栏「⏻ 关闭服务」（无终端也能停；成果都在工作目录，不会丢）。
- 用户在对话里说「关掉服务」→ 你运行 `python3 scripts/serve_review.py --project <工作目录> --stop`（读 `review/serve.pid` 结束进程并清理）。
- 兜底：`kill $(cat <工作目录>/review/serve.pid)` 或 `lsof -ti :<端口> | xargs kill`。
> 启动新项目前先 `--stop` 掉旧项目的服务，避免多个服务堆叠占端口。

## 工作流总览

```
阶段0 启动应用 ──→ 阶段1 对齐+生成角色/场景/分镜(应用内看进度审核) ──→ 阶段2 分镜确认 ──→ 阶段3 样片/成片(应用内)
  建目录·开应用·配Key   ▲  角色三视图·场景·故事·机位                              低配样片→确认→成片
  (模型/参数应用内改)     │  (可反复确认, 接收用户参考素材)                                    │
                       └──────────────────── 修改 / 续集循环 ◄────────────────────────────┘
```

## 阶段 0：建目录 + 开应用 + 配 Key（硬性第一步）

用户第一次提出做短剧/视频时，**你就把工作目录建好、应用启动并打开**，不要在对话里长篇问规格。

1. **为本轮对话新建隔离项目目录**：选一个固定**总工作目录**（如 `<workspace>/sa_drama`），用 `--parent` 让脚本在其下自动建一个带唯一 id 的子目录：
   ```bash
   python scripts/init_project.py --parent /abs/path/sa_drama --title "<标题>"
   # 输出末行 PROJECT:<绝对路径> —— 记下它，本轮一切都用它（记为 $P）
   ```
   - **每轮对话都新建**（不同对话各自隔离，旧历史不串）；**本轮内复用同一 `$P`**，不要再新建。
2. 按上面「❗启动协议」分离常驻启动应用（首次还没资产也能开），把真实链接放进回复，说明请在「设置」填 Key、再点「开始生成」。
3. **配 Key**：用户在 `#config` 填 → 保存即写 `.sa_key`、即时生效。（若工作区已注入环境变量 `SENSEAUDIO_API_KEY`，应用会显示「已配置」，无需填。）

> Key 来源优先级：环境变量 `SENSEAUDIO_API_KEY` > 项目 `.sa_key`。改模型/参数都在应用「设置」里随时进行。
> 不确定接口细节查 [references/senseaudio-api.md](references/senseaudio-api.md)。

## 阶段 1：对齐需求 + 生成人设/场景

**目标：** 把构想落成可执行规格——登场人物（含三视图）、场景、故事、机位。

1. 用 [templates/brief.md](templates/brief.md) 逐项对齐：题材、画幅、风格、人物、场景、故事、机位。缺口处提问，可多轮反复确认。
2. **接收用户参考素材**：图像/视频/音频存到 `assets/refs/`。
   **❗参考图必须对应正确角色，不能靠顺序猜**：用户一次给多张人物图时，先逐张看图确认谁是谁，再按角色落盘命名（如 `uploaded_<角色id>.png`）写进对应角色任务；不确定就问。
   最稳：让用户在应用里**对着该角色卡片上传/「📁 工作目录」选图**（落到哪张卡片就是哪个角色）。生成后核对卡片参考图与提示词是否同一人。
3. **写阶段1 的 `plan.json`**——只放 `characters` + `scenes`：
   - **角色出一张三视图合图**：不要带 `views`（分张 = 3 倍价钱）；带 `gender` 锁性别、`build` 写身高/体型。（图像统一用一个模型，不分样片/成片；省积分靠视频侧 480p→1080p。）
   - **统一画风**：先做一个角色当基准，其余角色 `style_ref:"<基准角色id>"` 出同款画风（详见 [references/prompting-guide.md](references/prompting-guide.md)）。
   - **场景只写环境、无人物**（脚本对 scene 已强制追加「无人物」兜底）。
4. 按启动协议分离常驻启动应用（`--plan` 把任务备为「待生成」），把真实链接放进回复。
5. **续作阶段2/3**：用户认可阶段1（或说「继续」）后，先 `status.py` 看 `next_stage`，只为缺失/下一阶段写任务：
   阶段2（`shots`，带 `characters`/`scene`）→ 认可后再推阶段3（`clips` 带 `shots`/`characters`）→ 阶段4（`exports` 拼接导出）。**不要重推已完成的阶段。**

**门禁：** 页面把 `通过` 的资产标 `approved`、`需修改` 标 `draft`（写进 `state.json`）。续作前用 `status.py` 看完成情况，只处理未通过/缺失项。

## 阶段 2：分镜

把故事拆成一组**分镜机位图**（每镜一张），自动参考阶段1 的人设图+场景图，prompt 里写清景别/机位/动作/**比例**。
分镜确认后进入阶段3——**视频以分镜图作参考生成**（不用首/尾帧）。详见 [references/generation-modes.md](references/generation-modes.md)。

## 阶段 3：视频片段（样片生成 / 成片生成 两个子页）

视频片段在侧边栏拆成 **「样片生成」「成片生成」两个子页**；**样片(480p)与成片(720p/1080p)各自独立保留**，互不覆盖。

1. **你（AI）按剧情把 `clips` 任务备好**（带 `shots`、`characters`、`duration`，**不要带画幅/分辨率/样片标记进提示词**）`POST /api/plan`，并在对话里跟用户说明已备好哪些片段。
   > clip 任务**不用写 `sample`**——出样片还是成片由用户在对应子页触发时决定。
2. **用户自己选**：在「样片生成」子页点「**一键生成样片**」先出 480p 快速预览；不满意就让你调该片段的提示词/参考图（你改 plan 重推或用户在卡片改），重出样片。
3. 满意后到「成片生成」子页点「**一键生成成片**」出高清（也可只对某张卡片单独「生成成片」）。两个子页可分别一键，也可都点。
4. 成本对比可给：
   ```bash
   python scripts/estimate_cost.py --video-res 480p --video-seconds 5
   python scripts/estimate_cost.py --video-res 1080p --video-seconds 8
   ```

**默认值：** 样片 480p / 5s；成片 720p 起步，1080p 用于定稿镜头。竖屏短剧 `ratio=9:16`（画幅由配置控制，不写进提示词）。

## 阶段 4：导出成片（把片段按剧情顺序拼成整片）

所有视频片段确认后，可把它们**按剧情时间顺序拼接导出**成一条完整成片（应用左侧「成片导出」类目，阶段4；需要用户机器装了 ffmpeg）。
- **你（AI）按用户需求/剧情排定播放顺序**，`POST /api/plan` 备一条 `exports` 任务（草稿）：`order` 是 clip id 的有序列表（决定拼接先后），只放已生成的 clip。
- 用户在「成片导出」分类点「**合成导出**」触发；后端 `concat_clips.py` 把各段归一化到统一画幅/帧率/音轨（兼容样片+成片混排）再无损拼接，完成后卡片里可预览/下载。
- 想换顺序/增删片段：你改 `order` 再推一条（或用户让你重排），点「重新导出」即可。
- **打包下载全部**：导出页顶部有「⬇ 打包下载全部」，把中间图像（人设/场景/分镜）+ 视频片段 + 成片整片打成一个 zip 下载。
```bash
curl -s http://127.0.0.1:<端口>/api/plan -d '{"tasks":[{"category":"exports","id":"export_01","title":"完整成片","order":"clip_01,clip_02,clip_03"}]}'
```

## plan.json 形如

字段对应 `gen_*.py` 参数；参考图字段统一用 **`references`（数组）**（写成单数 `reference` 也会被归一）：
```json
{"tasks":[
  {"category":"characters","id":"char_01","name":"林夏","prompt":"…身份锚点+外观+体型…","gender":"女","build":"娇小，比男主矮一头"},
  {"category":"scenes","id":"scene_01","name":"便利店","prompt":"…只写环境，无人物…"},
  {"category":"shots","id":"shot_01","prompt":"中景，两人在玄关对话；男主比女主高约一头","characters":"char_01,char_02","scene":"scene_01"},
  {"category":"clips","id":"clip_01","prompt":"…镜头动作+比例…","characters":"char_01,char_02","shots":"shot_01","duration":5},
  {"category":"exports","id":"export_01","title":"完整成片","order":"clip_01,clip_02,clip_03"}
]}
```

## 脚本速查

> 图/音/视频一般**不用你手敲命令逐个跑**——写进 `plan.json` 交给 `serve_review.py --plan` 并行生成、显示进度。
> 下面的 `gen_*.py` 是这些任务底层调用的脚本（应用「重新生成」也走它们），单独调试时才直接用。

| 任务 | 命令 |
|------|------|
| **初始化项目(每轮唯一)** | `python scripts/init_project.py --parent /abs/sa_drama --title "..."` → 建唯一子目录、打印 `PROJECT:<路径>`。也可 `--project <显式目录>` |
| **查项目进度(续作前必看)** | `python scripts/status.py --project "$P"` → 各阶段已完成/已通过资产 + `next_stage`（读 state.json） |
| **启动唯一前端** | `python3 scripts/serve_review.py --project "$P" --port 8765 --daemon [--plan …] [--concurrency 4]` → `cat "$P/review/serve_url.txt"` 取真实 URL |
| **停止服务** | `python3 scripts/serve_review.py --project "$P" --stop`（或用户点「⏻ 关闭服务」） |
| 保存 Key（一般由应用 `#config` 完成） | `python scripts/save_key.py --project "$P" --key "<api_key>"`（或 `--key -` 从 stdin 读） |
| 生成前检查 Key | `python scripts/check_key.py --project "$P"`（退出码 2 = 缺 Key，引导去 `#config`） |
| 角色三视图（一张设定图，默认） | `python scripts/gen_image.py --project "$P" --type character --id char_01 --name 林夏 --prompt "..." --ratio 16:9` |
| 角色分张参考图（慎用·3 倍价钱） | `… --type character --id char_01 --prompt "..." --views front,side,back`（仅用户明确要分张时） |
| 场景图 | `… --type scene --id scene_01 --name 便利店 --prompt "..."` |
| 分镜机位图 | `… --type shot --id shot_01 --prompt "..." --characters char_01 --scene scene_01` |
| 生成样片（480p 最省） | `python scripts/gen_video.py --project "$P" --id clip_01 --sample --prompt "..." --shots shot_01 --characters char_01 --duration 5` |
| 生成成片 | `… --id clip_01 --resolution 1080p --prompt "..." --shots shot_01 --characters char_01 --duration 8` |
| 成本预估 | `python scripts/estimate_cost.py --project "$P"` |
| 导出成片（按序拼接，需 ffmpeg） | `python scripts/concat_clips.py --project "$P" --id export_01 --ids clip_01,clip_02,clip_03 --title 成片`（一般写进 `exports` plan 任务由应用触发） |

## 项目结构（总目录固定，每轮对话一个隔离子目录）

子目录内所有路径由 `project_utils.SUBDIRS` 单一定义、自动创建：
```
<总工作目录>/                  # 用户决定的唯一根（如 <workspace>/sa_drama）
└── <标题>_<时间>_<随机>/      # 每轮对话一个项目（init_project --parent 自动建，互相隔离）
    ├── state.json            # 唯一状态源：含 config、各资产；见 templates/state-schema.md
    ├── .sa_key               # API Key（用户在应用 #config 填，不进 git、不展示）
    ├── assets/               # characters/ scenes/ shots/ refs/
    ├── output/               # 成片输出
    ├── review/               # 实时应用产物：plan.json、serve_url.txt、serve.pid、serve.log
    └── docs/                 # 剧本 / 说明
```
> 改目录结构只改 `project_utils.SUBDIRS` 一处；要某类目录绝对路径用 `pu.subdir(project, "shots")`。
> 配置不落单独文件，统一存在 `state.json` 的 `config` 字段（用户在「设置」里改 → `/api/config` 落盘）。

## 修改 / 续集循环

大多数修改用户**直接在应用里完成**（改卡片提示词/参考图/模型后「重新生成」），无需你介入。
需要你帮忙时，先 `status.py` 看各项 `review`/完成情况，**只重做仍 `需修改`/缺失的项**。

| 用户诉求 | 回到 | 操作 |
|----------|------|------|
| 性别错 / 衣服对不上 / 角色消失或重复 | 阶段1 | 重做该项：角色带 `gender`、新角色 `style_ref` 对齐画风；分镜/视频带 `characters`（注入锚点+各角色图），prompt 写清"画面共 N 人、谁在做什么" |
| 改角色/场景/分镜外观 | 阶段1/2 | 用户在卡片改提示词/参考图后「重新生成」；或你改 plan 重生成该项 |
| 镜头内容/构图不对 | 阶段2 | 改分镜图（它是视频的参考），再重出该 clip |
| 画质/时长不满意 | 阶段3 | 升/调参数重出 |
| 续写下一段剧情 | 阶段1→3 | 新增分镜→新 clip（参考新分镜图）；需承接旧片用 `--prev-video <已托管 http(s) URL>`（见 generation-modes.md） |

## 硬性规则速查（详见上文对应小节）

- **唯一前端** = 实时应用，`--daemon` 常驻、读 `serve_url.txt` 取真实端口；不要前台、不要 run_in_background、不要再生成静态确认页。
- **没 Key 引导去 `#config`，绝不 mock**；`--mock` 只属 selftest。
- **你只准备、用户在 UI 触发生成**；别说"已生成完"。
- **续作先 `status.py`**（读 state.json），只补缺失/下一阶段，绝不重推已通过项。
- **阶段顺序**：人设+场景 → 分镜 → 视频成片 → 导出；分镜/视频必带 `characters`(+`scene`)，参考图自动注入。
- **角色单张三视图**，不要 `views`（分张 = 3 倍价钱）；**场景图 = 空镜**（只画环境）。
- **视频 = 参考分镜图（+角色图）**，不用首/尾帧；用 `shots` 指定参考的分镜。
- **比例一致**：角色带 `build`，分镜/视频提示词显式写明人物之间、人物与场景/道具的大小比例，跨镜用同一套措辞。
- **配置信息不进提示词**：画幅（竖屏/9:16/16:9）、分辨率（480p/1080p）、时长（几秒）、样片/成片 等都由**配置或任务字段**控制、用户可随时调，**一律别写进提示词**（如「5秒竖屏短剧样片」是多余的）。提示词只写画面内容/动作/镜头/光线/风格；其中的「比例」只指人物与场景的大小关系，不是画幅。
- **样片先于成片**（除非用户明确说直接出成片）；**只改受影响项**，不重生成已 `approved` 的资产。
- **Key 不落盘**：只用环境变量或 `.sa_key`，不写进 state.json / 不提交 git。

## 延伸阅读
- [references/senseaudio-api.md](references/senseaudio-api.md) — 接口、模型、价格、size 取值
- [references/generation-modes.md](references/generation-modes.md) — 阶段3 视频各模式与参数
- [references/prompting-guide.md](references/prompting-guide.md) — 提示词与一致性
- [templates/state-schema.md](templates/state-schema.md) — state.json 字段
- [templates/brief.md](templates/brief.md) — 阶段1 对齐清单
