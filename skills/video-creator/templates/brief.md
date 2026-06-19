# 阶段 1 需求对齐清单

逐项与用户确认，缺口处提问。对齐结果写入 `plan.json`（及可选的顶层 `story` 字段），**由用户在审核 UI 点「开始生成」**，助手不代触发生成。

## 整体
- 标题 / 题材（都市、悬疑、甜宠、古风…）
- 画幅：横屏 `16:9`（默认）/ 竖屏 `9:16`（短剧常用）
- 时长与篇幅：计划几个**独立 clip**（硬切拼接）；每 clip 时长 **推荐 5/10/15 秒**（详见 [prompting-guide.md](../references/prompting-guide.md)）
- 视觉风格：写实电影感 / 动画 / 国风 …（写入 `config.style`）
- 整体基调与情绪

## 登场人物（逐个）
- 姓名、年龄、性别、身份
- 外观锚点：无参考图时写入 plan `prompt`（身份 + 按需画风/表情/装备要点）；**有参考图时 prompt 从简**；资料卡布局由 [character-sheet.md](character-sheet.md) 自动追加
- 全片画风：写入 `config.style` 或在各角色 `prompt` 中说明
- `build`（身高/体型，如「娇小，比男主矮一头」）写入角色任务字段
- 是否有参考图（用户在角色卡片上传，或 `save_ref.py` 落盘到 `assets/refs/`）

## 场景（逐个）
- 场景名称、类型（住宅/商业/自然/科幻等）
- 主体空间 + 2–4 个关联区域；时间、天气、光线、关键道具、色调
- 无参考图时写入 plan `prompt`（可按 [environment-bible.md](environment-bible.md) 快速模式：名称+主体+时间天气+风格）；**有参考图时 prompt 从简**
- 可选：动线节点 3–5 个、品质对标（或写入 `config.style`）
- 是否有参考图（用户在场景卡片上传）

## 故事
- 一句话梗概（logline）→ 写入 plan 顶层 `story.logline`
- **节拍清单** → `story.beats[]`，每个节拍对应 1 个 shot + 1 个 clip
- 每个节拍标注建议时长（写入 clip 任务的 `duration`）

## 机位 / 镜头语言
- 景别（远/全/中/近/特写）、机位（平/俯/仰/过肩）、运动（固定/推拉/横摇/跟拍）

> 对齐充分后，把角色三视图与场景图写进 `plan.json`，
> **首轮**按 SKILL.md「启动协议」`serve_review --daemon [--plan …]`；
> **之后各阶段**用 `push_plan.py --project "$P" --plan …` 推到**同一服务**，勿再 `--daemon`。
> 读 `review/serve_url.txt` 取 URL（全程同一链接），**告知用户在 UI 点「开始生成」并结束回合**；用户满意并标记通过后，再备阶段 2 分镜草稿。
