"""生成图像资产：角色三视图 / 场景图 / 分镜机位图 / 角色入景合成图。

每次生成都会：下载图片到项目 assets/、更新 state.json、打印结果路径。

示例：
  # 角色三视图（一张含正/侧/背的设定图）
  python gen_image.py --project P --type character --id char_01 \
      --name 林夏 --prompt "25岁女性，短发，米色风衣" --ratio 16:9

  # 角色单张参考图（正面/侧面/背面分别出图，共用 seed 保持一致）
  python gen_image.py --project P --type character --id char_01 \
      --prompt "..." --views front,side,back

  # 场景 Environment Bible（六模块空镜合图）
  python gen_image.py --project P --type scene --id scene_01 \
      --name 便利店 --prompt "深夜便利店，收银区与货架通道，雨后冷白荧光"

  # 分镜机位图（可用角色/场景图作参考保持一致）
  python gen_image.py --project P --type shot --id shot_01 \
      --prompt "中景，林夏推开玻璃门" --reference assets/characters/char_01_front.png

  图像统一用一个模型（不区分样片/成片）。（--mock 仅 selftest 自检用，勿作交付）
"""
import argparse
import os
import sys

import sa_client as sa
import project_utils as pu

# 1x1 占位 PNG（mock 模式用）
_MOCK_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6364f8cf00000201010073ad5d" "1c0000000049454e44ae426082"
)

# 场景环境设定板（Environment Bible）默认模板
ENVIRONMENT_BIBLE_BODY = (
    "用途：用于后续分镜/视频的空间统一系统，需具备真实逻辑、连续镜头可行性与长期叙事一致性；"
    "这是环境设定板（Environment Bible），不是普通单张效果图。"
    "视觉规范：电影级视觉排版，分区清晰有条理，气质克制统一，禁止地产广告感、网红风、塑料感。"
    "模块1世界观主视觉：完整展示主体空间及周边关联区域，体现真实使用痕迹与明确时间/天气氛围。"
    "模块2空间结构：轴测或等距结构示意，展示完整布局、核心设施与家具位置、采光逻辑与人物动线（画面中无人物）。"
    "模块3空间镜头参考：各区域统一风格的多角度空镜——全景 establishing、中景 medium、"
    "主观视角站位 POV、动线方向 tracking、情绪氛围 mood；结构、道具、灯光、材质跨镜头完全一致。"
    "模块4延展环境：与主空间呼应的外部或周边环境，使内外形成统一世界观。"
    "模块5镜头动线：一条贯穿式移动路径按节点串联，具备电影调度感，支持长镜头跟拍与空间穿梭。"
    "模块6视觉系统：统一空间建筑语言、材质体系、灯光逻辑、摄影风格、色彩、焦段景深、运镜节奏与时间天气氛围。"
    "全图必须是同一原创场景体系，各分区空间逻辑一致。"
    "严格空镜：不要出现任何人物、角色或人影；不要添加文字，不要水印。"
)


def environment_bible_suffix(has_reference):
    """场景合图后缀：Environment Bible 六模块布局；具体画风由参考图 / prompt / config.style 决定。"""
    intro = ("基于参考图，为同一原创场景制作完整的环境设定板（Environment Bible）。"
             if has_reference else "为原创场景制作完整的环境设定板（Environment Bible）。")
    return f"{intro}要求：{ENVIRONMENT_BIBLE_BODY}"

# 人设三视图默认模板（官方设定资料卡式排版，仅结构与输出约束）
CHARACTER_SHEET_BODY = (
    "整体为官方设定资料卡式排版：白色背景，分区清晰、布局有条理，设定集插画资料风格，"
    "平面均匀光照，轻微阴影，禁止复杂场景背景。"
    "第一区横向陈列完整三视图：正面、侧面、背面全身站姿，比例一致。"
    "第二区展示同一角色的面部表情变化（如平静、微笑、惊讶等，保持同一脸型、发型与发色）。"
    "第三区分解陈列服装与装备细节（外衣、内搭、鞋帽、配饰、道具等各部位拆分展示，"
    "颜色与材质与主视图一致）。"
    "全图必须是同一个原创角色，脸型、发型、发色、眼睛颜色、体型、服装结构、颜色、"
    "鞋子和配饰在各分区保持一致。"
    "不要添加文字，不要水印，不要多余无关人物，不要擅自改动服装设计。"
)

VIEW_SUFFIX = {
    "front": "正面全身站姿，角色面向镜头，同一原创角色，白底设定资料卡分区，平面均匀光照，无文字无水印",
    "side": "正侧面全身站姿，同一角色同样服装与配饰，白底设定资料卡分区，平面均匀光照，无文字无水印",
    "back": "背面全身站姿，同一角色同样服装与配饰，白底设定资料卡分区，平面均匀光照，无文字无水印",
}


def character_sheet_suffix(has_reference):
    """人设合图后缀：设定资料卡式布局与一致性约束；具体画风由参考图 / prompt / config.style 决定。"""
    intro = ("基于参考图，为同一原创角色制作官方设定资料卡式角色设定图。"
             if has_reference else "为原创角色制作官方设定资料卡式角色设定图。")
    return f"{intro}要求：{CHARACTER_SHEET_BODY}"


def _emit(msg, on_log=None):
    print(msg)
    if on_log:
        on_log(msg)


def gen_one(model, prompt, size, reference, seed, dest, mock, use_async):
    if mock:
        with open(dest, "wb") as f:
            f.write(_MOCK_PNG)
        return dest
    if use_async:
        url = sa.image_async(model, prompt, size=size, reference=reference, seed=seed)
    else:
        url = sa.image_sync(model, prompt, size=size, reference=reference, seed=seed)
    return sa.download(url, dest)


def run_image_generation(project, *, img_type, item_id, prompt, name="", reference=None,
                         style_ref=None, gender=None, build=None, scene=None, characters=None,
                         views=None, ratio=None, model=None, seed=None, async_hd=False,
                         mock=False, on_log=None):
    """生成图像并更新 state。成功返回 None，失败抛出 sa.APIError。"""
    state = pu.load_state(project)
    pu.use_project_key(project)
    if mock:
        _emit("⚠ MOCK：仅供 selftest 自检，写占位文件，切勿作为成品交付。", on_log)
    else:
        pu.require_key(project)

    if img_type not in pu.IMAGE_TYPE_KEYS:
        raise ValueError(f"未知 type: {img_type}")

    cfg = state["config"]
    img_cfg = cfg.get("image", {})
    ratio = ratio or cfg["ratio"]
    model = model or img_cfg.get("model") or sa.DEFAULT_IMAGE_MODEL
    use_async = async_hd or img_cfg.get("use_async", False)
    style = (cfg.get("style") or "").strip()

    size = sa.pick_size(model, ratio)
    key = pu.IMAGE_TYPE_KEYS[img_type]
    outdir = pu.subdir(project, key)
    os.makedirs(outdir, exist_ok=True)
    seed = seed if seed is not None else abs(hash(item_id)) % 2_000_000

    char_ids = pu.parse_id_list(characters)
    scene_id = scene
    base_prompt = prompt
    refs = [r.strip() for r in reference.split(",")] if reference else []

    if not refs and img_type == "shot":
        spec = {"characters": characters, "scene": scene, "references": []}
        pu.resolve_generation_refs(state, "shots", spec)
        refs = spec.get("references") or []
        if not char_ids:
            char_ids = pu.parse_id_list(spec.get("characters"))

    style_note = ""
    if img_type == "character":
        if not refs and style_ref:
            refs = [pu.character_image(state, style_ref) or style_ref]
        if refs:
            style_note = "，与参考图保持同一画风（统一渲染风格、同一世界观）"
    elif img_type == "scene" and refs:
        style_note = "，与参考图保持同一空间格局与世界观气质"
    if img_type == "shot":
        anchor = pu.character_anchor(state, char_ids)
        if anchor:
            base_prompt = anchor + "镜头：" + prompt

    seen, abs_refs = set(), []
    for r in refs:
        if not r:
            continue
        rp = pu.resolve_asset_path(project, r)
        if rp not in seen:
            seen.add(rp)
            abs_refs.append(rp)

    reference_img = abs_refs[0] if abs_refs else None
    if img_type == "shot" and len(abs_refs) > 1 and not mock:
        local = [r for r in abs_refs if not r.startswith(("http://", "https://", "data:"))]
        if len(local) > 1:
            board = os.path.join(pu.subdir(project, "refs"), f"{item_id}_board.png")
            if sa.composite_reference(local, board):
                reference_img = board
                base_prompt += ("。【参考图是“出场角色设定图 + 场景图”的横向拼贴，"
                                "请据此让每个角色的外观/服装/身高比例与各自设定一致、场景与设定一致；"
                                "输出为完整的单幅镜头画面，不要输出拼贴或分格】")

    cost = 0.0

    def _rel(p):
        return p if p.startswith(("http://", "https://", "data:")) else os.path.relpath(p, project)

    src_refs = [_rel(r) for r in abs_refs]
    record = {"id": item_id, "name": name, "prompt": prompt,
              "references": src_refs, "model": model, "status": "draft"}
    if gender:
        record["gender"] = gender
    if build:
        record["build"] = build

    if img_type == "character" and views:
        view_list = pu.parse_id_list(views) if isinstance(views, str) else list(views)
        three = {}
        gender_s = f"，{gender}" if gender else ""
        for v in view_list:
            vprompt = f"{prompt}{gender_s}{style_note}。{VIEW_SUFFIX.get(v, '')}"
            dest = os.path.join(outdir, f"{item_id}_{v}.png")
            gen_one(model, pu.apply_style(vprompt, style), size, reference_img, seed, dest, mock, use_async)
            three[v] = os.path.relpath(dest, project)
            cost += sa.estimate_image(model)
            _emit(f"  ✓ {v}: {dest}", on_log)
        record["three_view"] = three
        record["image"] = three.get("front") or next(iter(three.values()), None)
    else:
        if img_type == "character":
            gender_s = f"，{gender}" if gender else ""
            gen_prompt = (f"{prompt}{gender_s}{style_note}。"
                          f"{character_sheet_suffix(bool(abs_refs))}")
            ratio = ratio or "16:9"
            size = sa.pick_size(model, ratio)
        elif img_type == "scene":
            gen_prompt = (f"{prompt}{style_note}。"
                          f"{environment_bible_suffix(bool(abs_refs))}")
        else:
            gen_prompt = base_prompt
        dest = os.path.join(outdir, f"{item_id}.png")
        gen_one(model, pu.apply_style(gen_prompt, style), size, reference_img, seed, dest, mock, use_async)
        rel = os.path.relpath(dest, project)
        record["image"] = rel
        if img_type == "character":
            record["three_view"] = {"sheet": rel}
        cost += sa.estimate_image(model)
        _emit(f"  ✓ {dest}", on_log)

    if img_type == "shot":
        if scene_id:
            record["scene_id"] = scene_id
        if char_ids:
            record["characters"] = char_ids
            _emit(f"  ↳ 已注入角色锚点：{','.join(char_ids)}；参考图：{reference_img or '(无)'}", on_log)

    def _apply(st):
        items = st.setdefault(key, [])
        ex = pu.find(items, item_id)
        if ex:
            ex.update(record)
        else:
            items.append(record)
        pu.log(st, f"生成 {img_type} 图像 {item_id}（model={model}, ~{cost:.2f}元）")

    pu.update_state(project, _apply)
    _emit(f"已更新 state.json（{img_type}={item_id}，参考成本 ~{cost:.2f}元）", on_log)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--type", required=True, choices=list(pu.IMAGE_TYPE_KEYS))
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--reference", default=None, help="参考图（本地路径或URL），保持一致性")
    ap.add_argument("--style-ref", default=None, help="画风基准：另一角色 id 或图片路径")
    ap.add_argument("--gender", default=None, help="角色性别（character 用）")
    ap.add_argument("--build", default=None, help="身高/体型（character 用），如「娇小」「高挑」")
    ap.add_argument("--scene", default=None, help="shot 所属场景 id")
    ap.add_argument("--characters", default=None, help="shot 出场角色 id，逗号分隔")
    ap.add_argument("--views", default=None, help="角色分张出图：front,side,back")
    ap.add_argument("--ratio", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--async-hd", action="store_true")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    run_image_generation(
        args.project, img_type=args.type, item_id=args.id, prompt=args.prompt,
        name=args.name, reference=args.reference, style_ref=args.style_ref,
        gender=args.gender, build=args.build, scene=args.scene,
        characters=args.characters, views=args.views, ratio=args.ratio,
        model=args.model, seed=args.seed, async_hd=args.async_hd, mock=args.mock,
    )


if __name__ == "__main__":
    try:
        main()
    except sa.APIError as e:
        print(f"sa_client.APIError: {e}", file=sys.stderr)
        raise SystemExit(1)
