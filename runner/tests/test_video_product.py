"""Offline test of what a video's sample frames carry: frame outlines bought by the run, the product
checks that read them, judges on first / middle / last frame, the over-time charts and the two-clip
player in the report, and draws without seeds. The Runware API is replaced by fakes.

Run: uv run --project runner python runner/tests/test_video_product.py
"""
import base64
import io
import json
import os
import shutil
import tempfile

import cv2
import imageio_ffmpeg
import numpy as np
import yaml
from PIL import Image

from runware_eval import bench, judge, report, run, score
from runware_eval import video as video_mod

from harness import check, finish



# a textured "product" on a plain backdrop, 480x640
rng = np.random.default_rng(3)
H, W, BACK = 640, 480, 235
img = np.full((H, W, 3), BACK, np.uint8)
yy, xx = np.mgrid[0:H, 0:W]
prod = ((xx - 240) / 130) ** 2 + ((yy - 340) / 190) ** 2 < 1
tex = cv2.GaussianBlur(rng.integers(0, 255, (H, W, 3), dtype=np.uint8), (0, 0), 2)
img[prod] = (0.5 * tex[prod] + np.array([60, 90, 50])).clip(0, 255).astype(np.uint8)
N, FPS = 48, 24  # 2 seconds


def warp(i, zoom, dx=0.0):
    s = 1 + zoom * i / N
    M = np.float32([[s, 0, -W * (s - 1) / 2 + dx * i], [0, s, -H * (s - 1) / 2]])
    return cv2.warpAffine(img, M, (W, H), borderValue=(BACK,) * 3)


def hold(i):  # nothing but a faint wobble in the product's brightness
    f = img.astype(np.float32)
    f[prod] *= 1 + 0.02 * np.sin(i / 4)
    return f.clip(0, 255).astype(np.uint8)


def push(i):  # push-in and drift: the product stays itself, its place and size change
    return warp(i, 0.15, 0.6)


def recolour(i):  # the product slides to another hue, in place
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV).astype(np.int32)
    hsv[..., 0][prod] = (hsv[..., 0][prod] + int(70 * i / N)) % 180
    hsv[..., 1][prod] = np.clip(hsv[..., 1][prod] + int(90 * i / N), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)


def shrink(i):  # the product shrinks to a third of its width
    return warp(i, -0.66)


CLIPS = {"hold": hold, "push": push, "recolour": recolour, "shrink": shrink}

d = tempfile.mkdtemp()
src = os.path.join(d, "served")
os.makedirs(src)
Image.fromarray(img).save(os.path.join(d, "item.png"))
Image.fromarray((prod * 255).astype(np.uint8)).save(os.path.join(d, "item_product.png"))
for name, fn in CLIPS.items():
    w = imageio_ffmpeg.write_frames(os.path.join(src, f"{name}.mp4"), (W, H), fps=FPS, quality=8, macro_block_size=4)
    w.send(None)
    for i in range(N):
        w.send(np.ascontiguousarray(fn(i)).tobytes())
    w.close()

sent, outlined = [], []


def fake_task(task, **kw):
    sent.append(task)
    return {"status": "success", "taskUUID": task["taskUUID"], "cost": 0.2, "latency_s": 20.0, "seed": 4242,
            "videoURL": f"http://x/{task['_recipe']}.mp4"}


def fake_outline(url, path, model=None):
    """Stands in for background removal: everything that is not the plain backdrop is the product."""
    assert url.startswith("data:image/"), "frames are sent inline, never uploaded"
    frame = np.asarray(Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")).astype(int)
    m = cv2.morphologyEx(((np.abs(frame - BACK).max(axis=2) > 30) * 255).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(m).save(path)
    outlined.append(path)
    return 0.0006


run.api.run_task = fake_task
run.api.download = lambda url, path: shutil.copyfile(os.path.join(src, url.rsplit("/", 1)[1]), path)
run.mask_from = fake_outline
bench.ensure_media = lambda b, lock: [e.update(_url="http://m/" + e["path"], _size=(W, H)) or b["_url_sha"].update(
    {"http://m/" + e["path"]: "sha"}) for e in bench.media_entries(b).values()]

spec = {
    "title": "Video product test", "goal": "The product stays the same product for the whole clip.",
    "inputs": [{"path": "item.png", "regions": {"product": "item_product.png"}}],
    "evaluate": {
        "first_frame": {"metrics": [{"id": "mask_iou", "region": "product", "min": 0.9}]},
        "product": {"metrics": [
            {"id": "video_outline_hold", "min": 0.85, "label": "Outline held"},
            {"id": "video_outline_hold", "align": True, "min": 0.85, "label": "Shape held"},
            {"id": "video_product_area", "min": 0.6, "max": 1.6, "label": "Product size"},
            {"id": "video_product_drift", "max": 0.35, "label": "Product colours"}]},
        "stability": {"metrics": [{"id": "video_color_drift", "max": 40}, {"id": "video_motion"}]},
        "judged": {"metrics": [{"id": "vlm_same_object"}, {"id": "vlm_checklist", "questions": ["Is the product whole?"]}]},
    },
    "budget": {"maxSpend": 5}, "draws": 2,
    "recipes": [{"id": n, "model": "test:1@1", "taskType": "videoInference", "price": 0.2,
                 "params": {"inputs": {"frameImages": ["$input"]}, "_recipe": n}} for n in CLIPS],
}
path = os.path.join(d, "bench.yaml")
yaml.safe_dump(spec, open(path, "w"))
b = bench.load(path)
bench.ensure_media(b, None)

# ---- draws: no seed is sent, every draw is its own call
jobs = bench.jobs(b, "full")
check("two draws per recipe, each with its own cache key", len(jobs) == 8 and len({j["hash"] for j in jobs}) == 8)
check("no seed goes out with the request", all("seed" not in j["task"] for j in jobs))
check("the same draw keeps its key between runs", [j["hash"] for j in jobs] == [j["hash"] for j in bench.jobs(b, "full")])
check("the smoke round is the first draw", [j["seed"] for j in bench.jobs(b, "smoke")] == [1] * 4)
pinned = bench.load(path)
bench.ensure_media(pinned, None)
pinned["recipes"][0]["params"]["seed"] = "$seed"
pj = [j for j in bench.jobs(pinned, "full") if j["recipe"] == "hold"]
check("a recipe that asks for `$seed` gets the draw number as its seed", [j["task"]["seed"] for j in pj] == [1, 2])
try:
    bench.jobs({**b, "seeds": [1, 2, 3]}, "full")
    check("the old `seeds:` list is refused with the new name", False)
except ValueError as err:
    check("the old `seeds:` list is refused with the new name", "draws" in str(err))

# ---- run: outlines are bought for the sample frames, and the first frame's is where image checks look
out = os.path.join(d, "runs", "full")
os.makedirs(out)
rows = run.execute(jobs, out, maxSpend=5, workers=2, log=lambda *a: None, b=b)
good = [r for r in rows if r["status"] == "success"]
check("every clip ran", len(good) == 8, str([r.get("error") for r in rows if r["status"] != "success"]))
check("five frame outlines per clip, sent inline", len(outlined) == 8 * video_mod.SAMPLES
      and all(abs(r["eval_cost"] - 0.003) < 1e-9 for r in good), f"{len(outlined)} outlines")
check("the seed the model reports is kept with the result", all(r.get("seed_used") == 4242 for r in good))
vp = video_mod.paths(out, good[0]["file"])
check("the first frame has an outline for the image checks", os.path.exists(vp["first_mask"]))
n_before = len(outlined)
run.execute(jobs, out, maxSpend=5, workers=2, log=lambda *a: None, b=b)
check("a second run buys nothing again", len(outlined) == n_before and len(sent) == 8)

# a run folder from before frame outlines existed: the next run fills them in and books the cost
old = os.path.join(d, "runs", "older")
shutil.copytree(out, old)
shutil.rmtree(os.path.join(old, "masks"))
os.makedirs(os.path.join(old, "masks"))
run.execute(jobs, old, maxSpend=5, workers=2, log=lambda *a: None, b=b)
filled = run.read_results(old)
check("outlines missing from an existing folder are made on the next run, nothing is generated again",
      len(outlined) == n_before + 8 * video_mod.SAMPLES and len(sent) == 8
      and all(abs(r["eval_cost"] - 0.006) < 1e-9 for r in filled if r["status"] == "success"))
off = os.path.join(d, "runs", "off")
os.makedirs(off)
n_before = len(outlined)
run.execute(bench.jobs(b, "smoke"), off, maxSpend=5, workers=1, log=lambda *a: None, b={**b, "video": {"masks": False}})
check("`video: { masks: false }` buys none", len(outlined) == n_before)

# ---- score: the product checks
asked = []


class FakePanel(judge.Panel):
    def _ask(self, j, prompt, images, schema):
        asked.append((prompt, images))
        return {"key": "k", "judge": j, "status": "success", "cost": 0.0,
                "answer": {"answers": [{"q": 1, "answer": "yes"}, {"q": 2, "answer": "yes"}]}}


judge.Panel = FakePanel
judge.api.api_key = lambda: "test"
b["judgeWhen"] = {"maxFailedChecks": 99}
data = score.score_all(b, out, rows, judges=True, log=lambda *a: None)
got = {s["recipe"]: {m["label"]: m for m in s["metrics"]} for s in data["scored"] if s["seed"] == 1}
val = lambda r, l: got[r][l]["values"]["value"]
passed = lambda r, l: got[r][l].get("pass")
for r in CLIPS:
    print("  ", r, {l: (round(m["values"]["value"], 3) if m["status"] == "ok" else m["status"] + ": " + str(m.get("note")))
                    for l, m in got[r].items()})
check("first-frame outline check now runs on video", all(got[r]["Outline"]["status"] == "ok" and passed(r, "Outline") for r in CLIPS))
check("outline held: only the clip that stays in place passes",
      [r for r in CLIPS if passed(r, "Outline held")] == ["hold", "recolour"], f"push {val('push', 'Outline held'):.2f}")
check("shape held (aligned): a push-in passes, and so does a product that only shrinks",
      all(passed(r, "Shape held") for r in CLIPS), f"shrink {val('shrink', 'Shape held'):.2f}")
check("product size: only the shrinking product fails", [r for r in CLIPS if passed(r, "Product size") is False] == ["shrink"],
      f"shrink {val('shrink', 'Product size'):.2f}, push largest {got['push']['Product size']['values']['largest']:.2f}")
check("product colours: only the recoloured product fails",
      [r for r in CLIPS if passed(r, "Product colours") is False] == ["recolour"],
      f"recolour {val('recolour', 'Product colours'):.2f}, push {val('push', 'Product colours'):.2f}, hold {val('hold', 'Product colours'):.2f}")
check("the first frame is the floor of product drift", got["recolour"]["Product colours"]["values"]["first"] < 0.15)
ser = got["recolour"]["Product colours"]["values"]["series"]
check("a value per sample frame, with its time", len(ser) == video_mod.SAMPLES and ser[0][0] == 0 and ser[-1][0] > 1.5
      and ser[-1][1] > ser[0][1])
check("frame-by-frame checks carry a series too", len(got["push"]["Video motion"]["values"]["series"]) > 10)

# without outlines the product checks do not run (no free pass)
bare = score.score_all(b, off, run.read_results(off), judges=False, log=lambda *a: None)
bm = {m["label"]: m for m in bare["scored"][0]["metrics"]}
check("no frame outlines: product checks are not run, the rest still is",
      all(bm[l]["status"] != "ok" for l in ("Outline held", "Product size", "Product colours")) and bm["Video motion"]["status"] == "ok")

# ---- judges see the first, middle and last frame
prompt, images = asked[0]
check("judges get the input and three frames", len(images) == 4 and "first, middle and last frame" in prompt)
check("questions are asked about the video, also the same-product one",
      "Answer about the video (images 2 to 4)." in prompt and "in the video (images 2 to 4) the same physical product" in prompt)
check("judge answers land on both checks", got["hold"]["Same object"]["status"] == "ok" and val("hold", "Judge checklist") == 1.0)
p = score.Pair(b, b["inputs"][0], vp["first"], None)
p.video = {"sample_files": [{"file": vp["sample"](k)} for k in range(video_mod.SAMPLES)]}
check("a check on a region still compares that region of the first frame only",
      len(judge.prepare(p, {"region": "product"}, b)) == 2 and len(judge.prepare(p, {"region": "product"}, b)[0]) == 2)

# ---- report
html = open(report.build(b, out, None, {}), encoding="utf8").read()
payload = json.loads(html.split("id='data'>", 1)[1].split("</script>", 1)[0])
it = payload["items"]["item|recolour"]
check("report: series travel with the shown output", set(it["series"]) >= {"Product colours", "Outline held", "Video motion"})
check("report: limits and units for the over-time charts", payload["seriesMeta"]["Product colours"]["max"] == 0.35
      and payload["seriesMeta"]["Outline held"]["unit"] == "IoU")
check("report: the over-time panel and the two-clip player are there",
      all(x in html for x in ("id='time-panel'", "id='tcharts'", "id='clip-b'", "id='clip-seek'", "id='clip-b-pick'")))
check("report: it speaks of draws, not seeds", "<dt>Draws</dt><dd>2</dd>" in html and "best draw" in html
      and "<dt>Seeds</dt>" not in html)
check("report: draws that are the very same file are called out",
      "Draws that are the same output" in html and "hold on item (2 draws)" in html)

finish()
