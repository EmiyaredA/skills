"""生成前的成本预估（参考价，折扣价，单位元，实际以平台结算为准）。

临时估算单次生成：
  python estimate_cost.py --image-model senseaudio-image-2.0-260319 --images 6
  python estimate_cost.py --video-res 1080p --video-seconds 8
  python estimate_cost.py --video-res 480p --video-seconds 5   # 样片对比

汇总当前项目（已做的图 + 计划/已生成的视频）：
  python estimate_cost.py --project P
"""
import argparse

import sa_client as sa
import project_utils as pu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--image-model", default="senseaudio-image-2.0-260319")
    ap.add_argument("--images", type=int, default=0)
    ap.add_argument("--video-res", default=None, choices=["480p", "720p", "1080p"])
    ap.add_argument("--video-seconds", type=int, default=0)
    args = ap.parse_args()

    total = 0.0
    if args.images:
        c = sa.estimate_image(args.image_model, args.images)
        total += c
        print(f"图像 ×{args.images}（{args.image_model}）：~{c:.2f}元")
    if args.video_res and args.video_seconds:
        c = sa.estimate_video(args.video_res, args.video_seconds)
        total += c
        print(f"视频 {args.video_res} ×{args.video_seconds}s：~{c:.2f}元")

    if args.project:
        state = pu.load_state(args.project)
        n_img = len(state.get("characters", [])) + len(state.get("scenes", [])) + len(state.get("shots", []))
        img_model = state["config"].get("image", {}).get("model_final", "senseaudio-image-2.0-260319")
        img_cost = sa.estimate_image(img_model, n_img)
        print(f"\n[项目汇总] 图像约 {n_img} 张（成片模型）：~{img_cost:.2f}元")
        total += img_cost
        for cl in state.get("clips", []):
            c = sa.estimate_video(cl.get("resolution", "720p"), cl.get("duration", 5))
            total += c
            print(f"  视频 {cl['id']} {cl.get('resolution')} {cl.get('duration')}s：~{c:.2f}元")

    print(f"\n合计参考成本：~{total:.2f}元")
    print("提示：先用 480p 样片确认效果，再升 720p/1080p 出成片，可显著省积分。")


if __name__ == "__main__":
    main()
