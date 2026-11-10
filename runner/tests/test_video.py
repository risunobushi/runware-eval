"""Offline test of the video path: synthetic clips with a known fault each, scored end to end.

Run: uv run --project runner python runner/tests/test_video.py
"""
import json
import os
import sys
import tempfile

import cv2
import imageio_ffmpeg
import numpy as np
import yaml
from PIL import Image

from runware_eval import bench, report, score

ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, extra)


# a textured "product" on a plain backdrop, 480x640
rng = np.random.default_rng(3)
H, W = 640, 480
img = np.full((H, W, 3), 235, np.uint8)
yy, xx = np.mgrid[0:H, 0:W]
prod = ((xx - 240) / 130) ** 2 + ((yy - 340) / 190) ** 2 < 1
tex = cv2.GaussianBlur(rng.integers(0, 255, (H, W, 3), dtype=np.uint8), (0, 0), 2)
img[prod] = (0.5 * tex[prod] + np.array([60, 90, 50])).clip(0, 255).astype(np.uint8)
cv2.putText(img, "LOGO", (180, 350), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (30, 30, 30), 3)

N, FPS = 48, 24  # 2 seconds


def still(i):
    return img


def pan(i):  # slow push-in and drift to the right
    s = 1 + 0.15 * i / N
    M = np.float32([[s, 0, -W * (s - 1) / 2 + 0.6 * i], [0, s, -H * (s - 1) / 2]])
    return cv2.warpAffine(img, M, (W, H), borderValue=(235, 235, 235))


def flicker(i):
    return (pan(i).astype(np.float32) * (1.12 if i % 6 < 3 else 0.88)).clip(0, 255).astype(np.uint8)


def drift(i):  # hue slides over time
    hsv = cv2.cvtColor(pan(i), cv2.COLOR_RGB2HSV).astype(np.int32)
    hsv[..., 0] = (hsv[..., 0] + int(40 * i / N)) % 180
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)


def melt(i):  # detail dissolves
    return cv2.GaussianBlur(pan(i), (0, 0), 0.1 + 6 * i / N)


def barred(i):  # the clean pan, padded to 9:16 with black bars top and bottom
    return cv2.copyMakeBorder(pan(i), 106, 106, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))


def cut(i):  # after one second the set is swapped for a dark one
    if i < N // 2:
        return pan(i)
    dark = pan(i).copy()
    dark[~prod] = (25, 25, 30)
    return dark


def stall(i):  # moves for the first half second, then stands still
    return pan(min(i, N // 4))


boil_rng = np.random.default_rng(11)


def boil(i):  # the product's surface is redrawn every frame
    f = pan(i).astype(np.int16)
    noise = cv2.GaussianBlur(boil_rng.integers(-60, 60, (H, W, 3)).astype(np.float32), (0, 0), 3)
    M = np.float32([[1 + 0.15 * i / N, 0, 0], [0, 1 + 0.15 * i / N, 0]])
    m = cv2.warpAffine(prod.astype(np.uint8), M, (W, H)) > 0
    f[m] += (noise[m] * 4).astype(np.int16)
    return f.clip(0, 255).astype(np.uint8)


CLIPS = {"still": still, "pan": pan, "flicker": flicker, "drift": drift, "melt": melt, "barred": barred,
         "cut": cut, "stall": stall, "boil": boil}

d = tempfile.mkdtemp()
out = os.path.join(d, "runs", "smoke")
os.makedirs(out)
Image.fromarray(img).save(os.path.join(d, "item.png"))
Image.fromarray((prod * 255).astype(np.uint8)).save(os.path.join(d, "item_product.png"))
rows = []
for name, fn in CLIPS.items():
    path = os.path.join(out, f"item__{name}__s1.mp4")
    fh, fw = fn(0).shape[:2]
    w = imageio_ffmpeg.write_frames(path, (fw, fh), fps=FPS, quality=8, macro_block_size=4)
    w.send(None)
    for i in range(N):
        w.send(np.ascontiguousarray(fn(i)).tobytes())
    w.close()
    rows.append({"input": "item", "recipe": name, "seed": 1, "model": "test:1@1", "status": "success",
                 "file": os.path.basename(path), "cost": 0.1, "latency_s": 30.0, "hash": name})
yaml.safe_dump({
    "title": "Video test", "goal": "A slow push-in on the product, nothing else changes.",
    "inputs": [{"path": "item.png", "regions": {"product": "item_product.png", "logo": {"box": [170, 310, 300, 365]}}}],
    "evaluate": {
        "first_frame": {"mode": "gate", "metrics": [
            {"id": "size_aspect", "aspect_tolerance": 0.02},
            {"id": "deltaE2000_region", "region": "product", "mean_max": 4.0, "label": "First frame colour"},
            {"id": "mask_iou", "region": "product", "min": 0.9},
            {"id": "video_letterbox", "max": 0.0, "label": "No black bars"}]},
        "motion": {"mode": "gate", "metrics": [{"id": "video_motion", "min": 0.5, "max": 20}, {"id": "video_duration", "min": 1.5}]},
        "stability": {"mode": "gate", "metrics": [
            {"id": "video_flicker", "max": 0.5}, {"id": "video_color_drift", "max": 4.0, "ignore_lightness": True},
            {"id": "video_sharpness_hold", "min": 0.5},
            {"id": "video_scene_hold", "max": 0.35}, {"id": "video_frozen_frames", "max": 0.2},
            {"id": "video_texture_stability", "max": 0.6}]},
    },
    "budget": {"max_usd": 1}, "seeds": [1],
    "recipes": [{"id": n, "model": "test:1@1", "taskType": "videoInference", "params": {}} for n in CLIPS],
}, open(os.path.join(d, "bench.yaml"), "w"))

b = bench.load(os.path.join(d, "bench.yaml"))
data = score.score_all(b, out, rows, judges=False, log=lambda *a: None)
got = {s["recipe"]: {m["label"]: m for m in s["metrics"]} for s in data["scored"]}
val = lambda r, l: got[r][l]["values"]["value"]
passed = lambda r, l: got[r][l].get("pass")
for r in CLIPS:
    print("  ", r, {l: (round(m["values"]["value"], 3) if m["status"] == "ok" else m["status"]) for l, m in got[r].items()})

check("all 9 clips scored", len(data["scored"]) == 9)
check("only the clip with a swapped set fails scene hold", [r for r in CLIPS if passed(r, "Video scene hold") is False] == ["cut"],
      f"cut {val('cut', 'Video scene hold'):.2f}, pan {val('pan', 'Video scene hold'):.2f}")
check("the still and the stalled clip fail frozen frames, nothing else does",
      [r for r in CLIPS if passed(r, "Video frozen frames") is False] == ["still", "stall"],
      f"stall {val('stall', 'Video frozen frames'):.2f}")
check("texture stability fails on the boiling surface (and on flicker and the cut), not on clean motion",
      [r for r in CLIPS if passed(r, "Video texture stability") is False] == ["flicker", "cut", "boil"],
      f"boil {val('boil', 'Video texture stability'):.2f}, pan {val('pan', 'Video texture stability'):.2f}")
check("only the padded clip fails the black-bar check", [r for r in CLIPS if passed(r, "No black bars") is False] == ["barred"],
      f"bars share {val('barred', 'No black bars'):.2f}")
check("the padded clip's picture is still compared fairly (aspect and colour pass)",
      passed("barred", "Aspect") and passed("barred", "First frame colour"))
check("duration read (2 s)", all(abs(val(r, "Video duration") - 2.0) < 0.15 for r in CLIPS))
check("still clip fails the motion gate, pan passes", passed("still", "Video motion") is False and passed("pan", "Video motion") is True,
      f"still {val('still', 'Video motion'):.2f}, pan {val('pan', 'Video motion'):.2f}")
check("flicker fails on the flickering clip and on the cut (a jump in brightness), nothing else",
      [r for r in CLIPS if passed(r, "Video flicker") is False] == ["flicker", "cut"])
check("only the drifting clip fails colour drift", [r for r in CLIPS if passed(r, "Video color drift") is False] == ["drift"])
check("only the melting clip fails sharpness", [r for r in CLIPS if passed(r, "Video sharpness hold") is False] == ["melt"])
check("first frame is compared with the input (only the clip that starts brighter fails)",
      [r for r in CLIPS if not passed(r, "First frame colour")] == ["flicker", "boil"])
check("outline check is not run without an output mask (no free pass)",
      all(got[r]["Outline"]["status"] != "ok" for r in CLIPS))
clean = [r for r in CLIPS if all(m.get("pass") is not False for m in got[r].values())]
check("only the clean pan passes everything that ran", clean == ["pan"], str(clean))
check("each fault is caught by its own check at least",
      all(passed(r, l) is False for r, l in (("cut", "Video scene hold"), ("stall", "Video frozen frames"),
                                             ("boil", "Video texture stability"), ("melt", "Video sharpness hold"))))
check("the padded clip fails nothing but the black-bar check",
      [l for l, m in got["barred"].items() if m.get("pass") is False] == ["No black bars"])

path = report.build(b, out, None, {})
html = open(path, encoding="utf8").read()
check("report: preview clips embedded", html.count("data:video/mp4;base64,") == 9)
check("report: frame strips embedded", "First, middle and last frame" in html)
check("report: headline names the clean clip", "Best against this brief's checks: <em>pan</em>" in html, html[html.index("<h1>"):html.index("</h1>")][:120])
print(f"   report {os.path.getsize(path) / 1e6:.1f} MB at {path}")

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
