"""生成图像资产：角色三视图 / 场景图 / 分镜机位图 / 角色入景合成图。

每次生成都会：下载图片到项目 assets/、更新 state.json、打印结果路径。

示例：
  # 角色三视图（一张含正/侧/背的设定图）
  python gen_image.py --project P --type character --id char_01 \
      --name 林夏 --prompt "25岁女性，短发，米色风衣" --ratio 16:9

  # 角色单张参考图（正面/侧面/背面分别出图，共用 seed 保持一致）
  python gen_image.py --project P --type character --id char_01 \
      --prompt "..." --views front,side,back

  # 场景图
  python gen_image.py --project P --type scene --id scene_01 \
      --name 便利店 --prompt "深夜便利店内部，冷白光"

  # 分镜机位图（可用角色/场景图作参考保持一致）
  python gen_image.py --project P --type shot --id shot_01 \
      --prompt "中景，林夏推开玻璃门" --reference assets/characters/char_01_front.png

  --sample 用配置的「样片模型」出草稿（默认与成片同为 2.0，可在应用设置里改便宜模型）。（--mock 仅 selftest 自检用，勿作交付）
"""
import argparse
import os

import sa_client as sa
import project_utils as pu

# 1x1 占位 PNG（mock 模式用）
_MOCK_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6364f8cf00000201010073ad5d" "1c0000000049454e44ae426082"
)

# 场景图后缀：强制空镜，避免模型自作主张往场景里塞人物（场景=环境，人物留给分镜）
SCENE_SUFFIX = "。【空镜场景：只表现环境、布景、道具与光线，画面中不要出现任何人物、角色或人影】"

VIEW_SUFFIX = {
    "front": "正面全身，角色面向镜头，T-pose，纯色背景，设定集风格",
    "side": "正侧面全身，同一角色，同样服装，纯色背景，设定集风格",
    "back": "背面全身，同一角色，同样服装，纯色背景，设定集风格",
    "sheet": "角色三视图设定集：同一画面内并排展示正面、正侧面、背面全身，纯色背景，统一光照",
}

TYPE_MAP = {
    "character": ("characters", "assets/characters"),
    "scene": ("scenes", "assets/scenes"),
    "shot": ("shots", "assets/shots"),
}


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--type", required=True, choices=list(TYPE_MAP))
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--reference", default=None, help="参考图（本地路径或URL），保持一致性")
    ap.add_argument("--style-ref", default=None, help="画风基准：另一角色 id 或图片路径；新角色参考它出同一画风（如男孩参考女孩出同款二次元3D）")
    ap.add_argument("--gender", default=None, help="角色性别（character 用），写进身份锚点防止性别漂移")
    ap.add_argument("--scene", default=None, help="shot 所属场景 id；自动把场景图作参考")
    ap.add_argument("--characters", default=None, help="shot 出场角色 id，逗号分隔；自动注入角色锚点+参考图")
    ap.add_argument("--views", default=None, help="角色分张出图，逗号分隔：front,side,back")
    ap.add_argument("--ratio", default=None, help="覆盖项目默认画幅")
    ap.add_argument("--model", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--sample", action="store_true", help="用配置的样片模型出草稿（默认与成片同款，可在设置里改便宜模型）")
    ap.add_argument("--async-hd", action="store_true", help="高分辨率用异步接口")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    state = pu.load_state(args.project)

    pu.use_project_key(args.project)
    if args.mock:
        print("⚠ MOCK：仅供 selftest 自检，写占位文件，切勿作为成品交付。")
    else:
        pu.require_key(args.project)
    cfg = state["config"]
    img_cfg = cfg.get("image", {})
    ratio = args.ratio or cfg["ratio"]
    model = args.model or (img_cfg.get("model_sample") if args.sample else img_cfg.get("model_final"))
    use_async = args.async_hd or img_cfg.get("use_async", False)
    style = (cfg.get("style") or "").strip()   # 项目级视觉风格（设置面板里改），追加到每条提示词保持全片统一

    def with_style(p):
        return f"{p}。【整体视觉风格：{style}，全片统一】" if style else p

    size = sa.pick_size(model, ratio)
    key, subdir = TYPE_MAP[args.type]
    outdir = os.path.join(args.project, subdir)
    os.makedirs(outdir, exist_ok=True)
    seed = args.seed if args.seed is not None else abs(hash(args.id)) % 2_000_000

    # 分镜：自动注入出场角色的身份锚点（防性别/服装漂移）+ 自动选参考图
    char_ids = [c.strip() for c in args.characters.split(",")] if args.characters else []
    scene_id = args.scene
    base_prompt = args.prompt
    # --reference 现在可传多张（逗号分隔）：分镜会把"各角色设定图 + 场景图"一并参考
    refs = [r.strip() for r in args.reference.split(",")] if args.reference else []
    style_note = ""
    if args.type == "character":
        if not refs and args.style_ref:
            refs = [pu.character_image(state, args.style_ref) or args.style_ref]
        if refs:
            style_note = "，与参考图保持同一画风（统一渲染风格、同一世界观）"
    if args.type == "shot":
        anchor = pu.character_anchor(state, char_ids)
        if anchor:
            base_prompt = anchor + "镜头：" + args.prompt
        if not refs:
            # 缺省：出场角色设定图（全部）+ 场景图，供拼贴参考
            refs = [pu.character_image(state, c) for c in char_ids]
            refs.append(pu.scene_image(state, scene_id))
    # 解析到项目目录下的绝对路径，去掉空值/重复
    seen, abs_refs = set(), []
    for r in refs:
        if not r:
            continue
        rp = r if r.startswith(("http://", "https://", "data:", "/")) else os.path.join(args.project, r)
        if rp not in seen:
            seen.add(rp)
            abs_refs.append(rp)
    # 图像 API 只接受单张参考图：多张时（分镜多角色+场景）拼成一张「参考拼贴」一起参考
    reference = abs_refs[0] if abs_refs else None
    if args.type == "shot" and len(abs_refs) > 1 and not args.mock:
        local = [r for r in abs_refs if not r.startswith(("http://", "https://", "data:"))]
        if len(local) > 1:
            board = os.path.join(args.project, "assets/refs", f"{args.id}_board.png")
            if sa.composite_reference(local, board):
                reference = board
                base_prompt += ("。【参考图是“出场角色设定图 + 场景图”的横向拼贴，"
                                "请据此让每个角色的外观/服装/身高比例与各自设定一致、场景与设定一致；"
                                "输出为完整的单幅镜头画面，不要输出拼贴或分格】")

    cost = 0.0
    # 记录里存「来源参考图」列表（人设/场景的原图），而不是发给 API 的拼贴板——这样卡片能显示用到的每一张
    def _rel(p):
        return p if p.startswith(("http://", "https://", "data:")) else os.path.relpath(p, args.project)
    src_refs = [_rel(r) for r in abs_refs]
    record = {"id": args.id, "name": args.name, "prompt": args.prompt,
              "reference": src_refs[0] if src_refs else None, "references": src_refs,
              "model": model, "status": "draft"}
    if args.gender:
        record["gender"] = args.gender

    if args.type == "character" and args.views:
        views = [v.strip() for v in args.views.split(",") if v.strip()]
        three = {}
        gender = f"，{args.gender}" if args.gender else ""
        for v in views:
            prompt = f"{args.prompt}{gender}{style_note}。{VIEW_SUFFIX.get(v, '')}"
            dest = os.path.join(outdir, f"{args.id}_{v}.png")
            gen_one(model, with_style(prompt), size, reference, seed, dest, args.mock, use_async)
            three[v] = os.path.relpath(dest, args.project)
            cost += sa.estimate_image(model)
            print(f"  ✓ {v}: {dest}")
        record["three_view"] = three
        record["image"] = three.get("front") or next(iter(three.values()), None)
    else:
        if args.type == "character":
            gender = f"，{args.gender}" if args.gender else ""
            prompt = f"{args.prompt}{gender}{style_note}。{VIEW_SUFFIX['sheet']}"
            ratio = args.ratio or "16:9"
            size = sa.pick_size(model, ratio)
        elif args.type == "scene":
            prompt = base_prompt + SCENE_SUFFIX
        else:
            prompt = base_prompt
        dest = os.path.join(outdir, f"{args.id}.png")
        gen_one(model, with_style(prompt), size, reference, seed, dest, args.mock, use_async)
        rel = os.path.relpath(dest, args.project)
        record["image"] = rel
        if args.type == "character":
            record["three_view"] = {"sheet": rel}
        cost += sa.estimate_image(model)
        print(f"  ✓ {dest}")

    if args.type == "shot":
        if scene_id:
            record["scene_id"] = scene_id
        if char_ids:
            record["characters"] = char_ids
            print(f"  ↳ 已注入角色锚点：{','.join(char_ids)}；参考图：{reference or '(无)'}")

    def _apply(st):
        items = st.setdefault(key, [])
        ex = pu.find(items, args.id)
        if ex:
            ex.update(record)
        else:
            items.append(record)
        pu.log(st, f"生成 {args.type} 图像 {args.id}（model={model}, ~{cost:.2f}元）")
    pu.update_state(args.project, _apply)   # 并发安全：重载最新 state 再写，避免并行生成互相覆盖
    print(f"已更新 state.json（{args.type}={args.id}，参考成本 ~{cost:.2f}元）")


if __name__ == "__main__":
    main()
