"""离线自检：用 --mock 跑通 初始化→出图→样片→实时审核服务 全流程，不消耗积分。

  python selftest.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run(args):
    print("$ python", " ".join(args))
    subprocess.check_call([sys.executable] + [os.path.join(HERE, args[0])] + args[1:])


def main():
    proj = tempfile.mkdtemp(prefix="vc_selftest_")
    run(["init_project.py", "--project", proj, "--title", "自检短剧", "--ratio", "9:16"])
    # 模拟 API Key 落盘 + 自动拾取
    run(["save_key.py", "--project", proj, "--key", "sk-selftest-dummy"])
    sys.path.insert(0, HERE)
    import json
    import project_utils as pu
    assert os.path.exists(pu.key_path(proj)), ".sa_key 未写入"
    assert "api_key" not in json.load(open(pu.state_path(proj), encoding="utf-8"))["config"], "Key 不应进入 config"

    run(["gen_image.py", "--project", proj, "--type", "character", "--id", "char_01",
         "--name", "林夏", "--prompt", "25岁女性，短发，米色风衣",
         "--views", "front,side,back", "--mock"])
    run(["gen_image.py", "--project", proj, "--type", "scene", "--id", "scene_01",
         "--name", "便利店", "--prompt", "深夜便利店，冷白光", "--mock"])
    run(["gen_image.py", "--project", proj, "--type", "shot", "--id", "shot_01",
         "--prompt", "中景，林夏推门", "--scene", "scene_01", "--mock"])
    run(["gen_video.py", "--project", proj, "--id", "clip_01", "--sample",
         "--prompt", "林夏推开便利店门回头一笑",
         "--shots", "shot_01", "--characters", "char_01", "--duration", "5", "--mock"])

    # 实时审核服务：规范化 payload 应包含全部分类与已生成资产
    import serve_review as sr
    payload = sr.ReviewState(proj).payload()
    cats = {c["key"]: c["count"] for c in payload["categories"]}
    assert cats.get("characters") == 1 and cats.get("scenes") == 1 and cats.get("clips") == 1, f"分类计数异常：{cats}"
    assert payload["items"]["characters"][0]["media"], "角色卡片缺少媒体"
    assert payload["has_key"], "应已配置 Key"
    print("\n实时审核服务 payload 正常：", cats)
    print("自检通过 ✓  临时项目：", proj)


if __name__ == "__main__":
    main()
