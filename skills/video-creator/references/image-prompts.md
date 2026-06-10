# 图像 Prompt 撰写规范

调用 `generate_image.py` 前阅读本文。多数图像 API 建议使用英文 prompt，除非提供商原生支持中文。

## 角色三视图

脚本会自动发起**三次独立调用**，分别生成正面、侧面、背面视图。

### Prompt 结构

```
[角色名], [年龄/体型], [发型], [服装], [显著特征].
画风: [来自 brief.style]. 情绪: [来自 brief.mood].
角色三视图设定稿, [VIEW] 视角, 全身, 中性灰背景,
比例一致, 无文字, 无水印.
```

### 一致性规则

- 三次调用中重复相同的外貌描述
- 仅更换视角关键词（`front`、`side`、`back`）
- 若用户上传了参考图，追加：`Match the reference character design closely.`
- 角色设定稿中避免出现场景元素 — 仅使用中性背景

### 示例

```
A young woman explorer, athletic build, short black hair, olive cargo jacket and boots,
brass compass on belt. Art style: cinematic semi-realistic. Mood: adventurous.
Character turnaround reference sheet, front view, full body, neutral gray background,
consistent proportions, no text, no watermark.
```

## 场景图

### Prompt 结构

```
[地点类型], [时间段], [天气], [氛围].
关键道具: [列表]. 画风: [brief.style]. 色调: [来自简报].
广角定场镜头, 无角色, 电影感构图, 无文字.
```

### 示例

```
Ancient forest clearing at dawn, mist between towering trees, golden light rays.
Key props: moss-covered stone altar, fireflies. Art style: cinematic fantasy.
Warm greens and amber tones. Wide establishing shot, no characters, no text.
```

## 分镜预览图

### Prompt 结构

```
场景: [场景描述]. 角色: [名称与位置].
动作: [beat.action]. 镜头: [beat.camera 或 medium shot].
画风: [brief.style]. 分镜单格, 单帧, 电影感构图.
```

### 示例

```
Scene: forest clearing at dawn with stone altar. Characters: explorer standing
center-frame facing altar. Action: she reaches toward glowing artifact on altar.
Camera: medium shot, slight low angle. Art style: cinematic fantasy.
Storyboard panel, single frame.
```

## 用户上传参考图时

优先级：

1. **用户上传** — 作为 `--reference` 路径；prompt 中注明「紧密匹配参考图」
2. **已批准的角色/场景资产** — 在分镜 prompt 中通过文字描述引用
3. **纯文本** — 从简报和角色档案中构建完整 prompt

## 修订循环

用户要求修改时：

- 定位问题资产（角色某视角、场景、分镜格）
- 仅重新生成受影响的图像
- 在用户明确批准前保持 `status: "draft"`
