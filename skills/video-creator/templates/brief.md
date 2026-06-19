# 阶段 1 需求对齐清单

逐项与用户确认，缺口处提问。对齐结果写入 `plan.json`（及可选 `story` 字段）。

工作流见 [SKILL.md](../SKILL.md)「助手协议」。

## 整体
- 标题 / 题材（都市、悬疑、甜宠、古风…）
- 画幅：横屏 `16:9`（默认）/ 竖屏 `9:16`
- 篇幅：几个**独立 clip**（硬切）；每 clip **推荐 5/10/15 秒**（见 [prompting-guide.md](../references/prompting-guide.md)）
- 视觉风格 → `config.style`
- 整体基调与情绪

## 登场人物（逐个）
- 姓名、年龄、性别、身份
- 无参考图：plan `prompt` 写身份锚点；**有参考图：prompt 从简**；布局见 [character-sheet.md](character-sheet.md)
- `build`（身高/体型）写入角色字段
- 参考图：用户在卡片上传

## 场景（逐个）
- 名称、类型、主体空间 + 关联区域；时间、天气、光线
- 无参考图：按 [environment-bible.md](environment-bible.md) 写 prompt；**有参考图：从简**
- 参考图：用户在卡片上传

## 故事
- `story.logline` · `story.beats[]`（每节拍 → 1 shot + 1 clip）
- 每 clip 的 `duration`

## 机位 / 镜头语言
- 景别、机位、运动（固定/推拉/横摇/跟拍）
