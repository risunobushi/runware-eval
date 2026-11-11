"""Offline test of the tool and text task types: upscale, removeBackground, imageMasking, vectorize,
caption and textInference. One small bench per type, run end to end (run, score, report) against a
fake Runware API that answers with outputs whose faults are known.

Run: uv run --project runner python runner/tests/test_tools_and_text.py
"""
import json
import os
import sys
import tempfile

import cv2
import numpy as np
import yaml
from PIL import Image

from runware_eval import adapters, bench, judge, label, report, run, score

ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, extra)


# ---- one input: a textured disc ("the product") on a plain backdrop, 400x300, with its reference outline
rng = np.random.default_rng(5)
H, W = 300, 400
yy, xx = np.mgrid[0:H, 0:W]
disc = (xx - 200) ** 2 + (yy - 150) ** 2 < 90 ** 2
img = np.full((H, W, 3), 232, np.uint8)
tex = cv2.GaussianBlur(rng.integers(0, 255, (H, W, 3), dtype=np.uint8), (0, 0), 1.2)
img[disc] = (0.6 * tex[disc] + np.array([70, 40, 30])).clip(0, 255).astype(np.uint8)
d = tempfile.mkdtemp()
Image.fromarray(img).save(os.path.join(d, "item.png"))
Image.fromarray((disc * 255).astype(np.uint8)).save(os.path.join(d, "item_product.png"))
open(os.path.join(d, "brief.txt"), "w", encoding="utf8").write("Write a one-line product title for a red ceramic mug.")

# ---- what the fake API hands back, by the URL it "serves"
small = (xx - 200) ** 2 + (yy - 150) ** 2 < 70 ** 2  # an outline that cuts 20 px into the product
SVG_GOOD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"><rect width="400" height="300" fill="#e8e8e8"/>'
            '<circle cx="200" cy="150" r="90" fill="#8a5a46"/><path d="M10 10 L 50 10 60 40 Z" fill="#222"/></svg>')
SVG_FAKE = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 400 300">'
            '<image width="400" height="300" xlink:href="data:image/png;base64,AAAA"/></svg>')


def rgba(a):
    return np.dstack([img, (a * 255).astype(np.uint8)])


FILES = {
    "up2.png": lambda p: Image.fromarray(img).resize((800, 600), Image.LANCZOS).save(p),
    "up2soft.png": lambda p: Image.fromarray(cv2.GaussianBlur(img, (0, 0), 2)).resize((800, 600), Image.BICUBIC).save(p),
    "same.png": lambda p: Image.fromarray(img).save(p),
    "cut_good.png": lambda p: Image.fromarray(rgba(cv2.GaussianBlur(disc.astype(np.float32), (0, 0), 1.0))).save(p),
    "cut_small.png": lambda p: Image.fromarray(rgba(small.astype(np.float32))).save(p),
    "cut_none.jpg": lambda p: Image.fromarray(img).save(p),
    "mask_good.png": lambda p: Image.fromarray((disc * 255).astype(np.uint8)).resize((200, 150), Image.NEAREST).save(p),
    "mask_empty.png": lambda p: Image.fromarray(np.zeros((H, W), np.uint8)).save(p),
    "good.svg": lambda p: open(p, "w").write(SVG_GOOD),
    "fake.svg": lambda p: open(p, "w").write(SVG_FAKE),
}
ANSWERS = {  # recipe id -> the result's own fields
    "up-sharp": {"imageURL": "http://x/up2.png"}, "up-soft": {"imageURL": "http://x/up2soft.png"},
    "up-not": {"imageURL": "http://x/same.png"},
    "cut-good": {"imageURL": "http://x/cut_good.png"}, "cut-small": {"imageURL": "http://x/cut_small.png"},
    "cut-none": {"imageURL": "http://x/cut_none.jpg"},
    "mask-good": {"maskImageURL": "http://x/mask_good.png", "detections": [{"x_min": 110, "y_min": 60, "x_max": 290, "y_max": 240}]},
    "mask-empty": {"maskImageURL": "http://x/mask_empty.png"},
    "vec-good": {"imageURL": "http://x/good.svg"}, "vec-fake": {"imageURL": "http://x/fake.svg"},
    "cap-good": {"text": "A round brown ceramic disc on a light grey backdrop."},
    "cap-long": {"text": "Certainly! Here is a caption. " + "This image shows a thing. " * 30},
    "txt-good": {"text": '{"title": "Red Ceramic Mug, 350 ml"}', "finishReason": "stop",
                 "usage": {"promptTokens": 20, "completionTokens": 12, "totalTokens": 32}},
    "txt-cut": {"text": '{"title": "Red Cer', "finishReason": "length",
                "usage": {"promptTokens": 20, "completionTokens": 4, "totalTokens": 24}},
}
sent, masks_made = [], []


def fake_task(task, **kw):
    sent.append(task)
    return {"status": "success", "taskUUID": task["taskUUID"], "cost": 0.01, "latency_s": 2.0,
            **ANSWERS[task["_recipe"]]}


run.api.run_task = fake_task
run.api.download = lambda url, path: FILES[url.rsplit("/", 1)[1]](path)
run.mask_from = lambda url, path: (masks_made.append(url), Image.fromarray((disc * 255).astype(np.uint8)).save(path), 0.0)[2]
bench.ensure_media = lambda b, lock: [e.update(_url="http://m/" + e["path"], _size=(W, H)) or b["_url_sha"].update(
    {"http://m/" + e["path"]: "sha"}) if not e["path"].endswith(".txt") else e.update(
    _text=open(os.path.join(b["_dir"], e["path"]), encoding="utf8").read()) for e in bench.media_entries(b).values()]


def go(name, task_type, params, evaluate, ids, inputs=None, seeds=(1,), extra=None):
    """Write a bench for one task type, run it against the fake API, score it and build its report."""
    path = os.path.join(d, f"bench_{name}.yaml")
    yaml.safe_dump({
        "title": f"{name} test", "goal": f"Compare {task_type} models.", "task": f"{task_type} on the item",
        "inputs": inputs or [{"path": "item.png", "regions": {"product": "item_product.png"}, **(extra or {})}],
        "evaluate": evaluate, "budget": {"maxSpend": 5}, "draws": len(seeds),
        "recipes": [{"id": i, "model": "test:1@1", "taskType": task_type, "params": {**params, "_recipe": i},
                     "price": 0.01} for i in ids],
    }, open(path, "w"))
    b = bench.load(path)
    out = os.path.join(d, "runs", name)
    os.makedirs(out, exist_ok=True)
    bench.ensure_media(b, None)
    jobs = bench.jobs(b, "full")
    rows = run.execute(jobs, out, maxSpend=5, workers=1, log=lambda *a: None, b=b)
    data = score.score_all(b, out, rows, judges=False, log=lambda *a: None)
    got = {s["recipe"]: {m["label"]: m for m in s["metrics"]} for s in data["scored"] if s["seed"] == 1}
    html = open(report.build(b, out, None, {}), encoding="utf8").read()
    return b, out, jobs, rows, data, got, html


val = lambda got, r, l: got[r][l]["values"]["value"]

# ---- upscale
b, out, jobs, rows, data, got, html = go(
    "upscale", "upscale", {"inputs": {"image": "$input"}, "upscaleFactor": 2},
    {"size": {"metrics": [{"id": "upscale_factor", "min": 1.9}, {"id": "size_aspect", "aspect_tolerance": 0.01}]},
     "fidelity": {"metrics": [{"id": "ssim_region", "region": "product", "min": 0.9},
                              {"id": "upscale_detail_gain", "region": "product", "label": "Detail gain"}]}},
    ["up-sharp", "up-soft", "up-not"], seeds=(1, 2))
check("upscale: the request carries the task type and the input", sent[0]["taskType"] == "upscale"
      and sent[0]["inputs"] == {"image": "http://m/item.png"} and sent[0]["upscaleFactor"] == 2)
check("no seed in the request: each draw is its own call, with its own cache key",
      len(jobs) == 6 and len({j["hash"] for j in jobs}) == 6 and len(rows) == 6)
check("the same job keeps its key between runs", [j["hash"] for j in jobs] == [j["hash"] for j in bench.jobs(b, "full")])
check("upscale: factor read from the delivered size", abs(val(got, "up-sharp", "Upscale factor") - 2) < 1e-6
      and val(got, "up-not", "Upscale factor") == 1 and got["up-not"]["Upscale factor"]["pass"] is False)
check("upscale: detail gain separates a sharp upscale from a soft one",
      val(got, "up-sharp", "Detail gain") > 2 * val(got, "up-soft", "Detail gain"),
      f"sharp {val(got, 'up-sharp', 'Detail gain'):.2f}, soft {val(got, 'up-soft', 'Detail gain'):.2f}")
check("upscale: an output that is not larger has no detail gain to measure",
      got["up-not"]["Detail gain"]["status"] == "error")
check("upscale: fidelity is read at the input's size (a faithful upscale passes)", got["up-sharp"]["Structure"]["pass"] is True)
check("upscale: outputs get a product outline like any picture", len(masks_made) == 6)

# ---- removeBackground
masks_made.clear()
ev_outline = {"outline": {"metrics": [{"id": "mask_iou", "region": "product", "min": 0.95},
                                      {"id": "mask_boundary_px", "region": "product", "max": 3},
                                      {"id": "mask_missing", "region": "product", "max": 0.05},
                                      {"id": "mask_extra", "region": "product", "max": 0.05},
                                      {"id": "alpha_edge_softness", "label": "Edge softness"}]}}
b, out, jobs, rows, data, got, html = go(
    "cutout", "removeBackground", {"inputs": {"image": "$input"}, "outputFormat": "PNG"}, ev_outline,
    ["cut-good", "cut-small", "cut-none"])
check("cut-out: its alpha is its outline (no paid mask call)", not masks_made
      and all(os.path.exists(os.path.join(out, "masks", r["file"].rsplit(".", 1)[0] + "_cut.png")) for r in rows))
check("cut-out: a clean cut passes every outline check",
      all(m.get("pass") is not False for m in got["cut-good"].values()), str({l: m.get("pass") for l, m in got["cut-good"].items()}))
check("cut-out: a cut that eats into the product fails overlap, missing and boundary, not extra",
      [l for l, m in got["cut-small"].items() if m.get("pass") is False] == ["Outline", "Mask boundary px", "Mask missing"],
      f"missing {val(got, 'cut-small', 'Mask missing'):.2f}, boundary {val(got, 'cut-small', 'Mask boundary px'):.1f} px")
check("cut-out: an output without transparency keeps everything (extra fails) and says so",
      got["cut-none"]["Mask extra"]["pass"] is False
      and "no transparency" in next(s["native"] for s in data["scored"] if s["recipe"] == "cut-none"))
check("cut-out: edge softness tells a soft edge from a hard one",
      val(got, "cut-good", "Edge softness") > 1 and val(got, "cut-small", "Edge softness") == 0)
check("cut-out: the report shows the cut-out, not the uncut picture",
      all(s.get("view", "").endswith("__cutout.png") and s.get("view_mask") for s in data["scored"]))

# ---- imageMasking
b, out, jobs, rows, data, got, html = go(
    "mask", "imageMasking", {"inputs": {"image": "$input"}}, {"outline": {"metrics": ev_outline["outline"]["metrics"][:4]}},
    ["mask-good", "mask-empty"])
check("mask: the result's maskImageURL is the output", [r["status"] for r in rows] == ["success", "success"] and not masks_made)
check("mask: a mask at another size is compared at the input's size", val(got, "mask-good", "Outline") > 0.97,
      f"IoU {val(got, 'mask-good', 'Outline'):.3f}")
check("mask: an empty mask fails overlap, missing and boundary",
      [l for l, m in got["mask-empty"].items() if m.get("pass") is False] == ["Outline", "Mask boundary px", "Mask missing"])

# ---- vectorize
b, out, jobs, rows, data, got, html = go(
    "vector", "vectorize", {"inputs": {"image": "$input"}},
    {"file": {"metrics": [{"id": "svg_images", "max": 0, "label": "Embedded bitmaps"}, {"id": "svg_shapes"},
                          {"id": "svg_nodes"}, {"id": "svg_colours"}, {"id": "svg_file_kb"}]},
     "fidelity": {"metrics": [{"id": "ssim_region", "min": 0.5, "label": "Looks like the input"}]}},
    ["vec-good", "vec-fake"])
check("vector: the SVG is kept as delivered", sorted(r["file"].rsplit(".", 1)[1] for r in rows) == ["svg", "svg"] and not masks_made)
check("vector: shapes, nodes and colours are counted",
      (val(got, "vec-good", "Svg shapes"), val(got, "vec-good", "Svg nodes"), val(got, "vec-good", "Svg colours")) == (3, 11, 3),
      str({l: m.get("values") for l, m in got["vec-good"].items()}))
check("vector: a bitmap in an SVG wrapper is caught", got["vec-fake"]["Embedded bitmaps"]["pass"] is False
      and got["vec-good"]["Embedded bitmaps"]["pass"] is True)
check("vector: the render is compared with the input", got["vec-good"]["Looks like the input"]["pass"] is True,
      f"SSIM {val(got, 'vec-good', 'Looks like the input'):.2f}")

# ---- caption: an image in, text out
text_checks = [{"id": "text_words", "max": 20, "label": "Length"}, {"id": "text_terms", "min": 1.0, "label": "Says what it is"},
               {"id": "text_banned", "max": 0, "banned": ["certainly", "here is"], "label": "No filler"},
               {"id": "text_reference_f1", "label": "Close to my caption"}]
b, out, jobs, rows, data, got, html = go(
    "caption", "caption", {"inputs": {"image": "$input"}, "prompt": "One sentence."},
    {"text": {"metrics": text_checks}, "picture": {"metrics": [{"id": "ssim_region", "min": 0.9}]}},
    ["cap-good", "cap-long"], extra={"terms": ["ceramic", "disc"], "reference": "A brown ceramic disc on a grey backdrop."})
check("caption: the text is the output, saved as a file", all(r["file"].endswith(".txt") and "url" not in r for r in rows)
      and open(os.path.join(out, rows[0]["file"]), encoding="utf8").read() == ANSWERS["cap-good"]["text"])
check("caption: a short caption with the terms passes; a padded one fails length and filler",
      all(m.get("pass") is not False for m in got["cap-good"].values())
      and [l for l, m in got["cap-long"].items() if m.get("pass") is False] == ["Length", "Says what it is", "No filler"])
check("caption: overlap with the reference caption is higher for the close one",
      val(got, "cap-good", "Close to my caption") > 0.7 > val(got, "cap-long", "Close to my caption"))
check("caption: a picture check is not run on text (no free pass, no nonsense value)",
      got["cap-good"]["Structure"]["status"] == "not_run")
check("caption: the report carries the text and its panel", ANSWERS["cap-good"]["text"] in html and "id='text-panel'" in html)
p = score.Pair(b, b["inputs"][0], os.path.join(out, "renders", rows[0]["file"].rsplit(".", 1)[0] + "__text.png"), None)
p.text = ANSWERS["cap-good"]["text"]
images, intro, subject = judge.prepare(p, {}, b)
check("caption: judges get the input picture and the text, and are asked about the text",
      len(images) == 1 and ANSWERS["cap-good"]["text"] in intro and subject == "the TEXT")
check("labeling page builds for text outputs", os.path.exists(label.build(b, out)[0]))

# ---- textInference: text in, text out
b, out, jobs, rows, data, got, html = go(
    "text", "textInference", {"messages": [{"role": "user", "content": "$input"}], "settings": {"maxTokens": 50}},
    {"format": {"metrics": [{"id": "text_json", "keys": ["title"], "min": 1, "label": "Valid JSON"},
                            {"id": "text_truncated", "max": 0, "label": "Not cut off"},
                            {"id": "text_regex", "pattern": r"\d+ ?ml", "min": 1, "label": "Has the volume"},
                            {"id": "text_output_tokens"}]}},
    ["txt-good", "txt-cut"], inputs=[{"path": "brief.txt"}])
check("text: a text input is sent as text, not uploaded",
      sent[-1]["messages"] == [{"role": "user", "content": "Write a one-line product title for a red ceramic mug."}])
check("text: finish reason and usage are kept with the result", rows[0]["finishReason"] == "stop"
      and rows[0]["usage"]["completionTokens"] == 12)
check("text: the complete answer passes; the cut-off one fails JSON, truncation and the pattern",
      all(m.get("pass") is not False for m in got["txt-good"].values())
      and [l for l, m in got["txt-cut"].items() if m.get("pass") is False] == ["Valid JSON", "Not cut off", "Has the volume"])
check("text: output tokens are read from the result", val(got, "txt-good", "Text output tokens") == 12)
check("text: the report shows the input text too", "Write a one-line product title" in html and "id='text-in'" in html)
p = score.Pair(b, b["inputs"][0], os.path.join(out, "renders", rows[0]["file"].rsplit(".", 1)[0] + "__text.png"), None)
p.text = ANSWERS["txt-good"]["text"]
images, intro, subject = judge.prepare(p, {}, b)
check("text: judges get the input text and no picture", images == [] and "red ceramic mug" in intro and "Red Ceramic Mug" in intro)
check("text: no controls on a text input", data["controls"] == [])

check("adapters: an output's kind follows its file and its task",
      [adapters.kind("a.svg"), adapters.kind("a.txt"), adapters.kind("a.png", "removeBackground"),
       adapters.kind("a.png", "imageMasking"), adapters.kind("a.png", "upscale")] == ["vector", "text", "cutout", "mask", "image"])

# ---- checks added after the full runs, each on a small made-up case
import importlib
import tempfile
from types import SimpleNamespace

from PIL import Image as _Image


def metric(mid):
    return importlib.import_module("runware_eval.metrics_lib." + mid).compute


def text_pair(t, **inp):
    return SimpleNamespace(text=t, input=inp, text_meta={})


FENCED = "```json" + chr(10) + '{"title": "Red Ceramic Mug 350 ml", "description": "A red mug. It holds 350 ml."}' + chr(10) + "```"
THOUGHT = "<think>The title needs the volume. Keep it short.</think>" + chr(10) + '{"title": "Red Mug"}'
check("text: a field of a JSON answer can be checked on its own (words, sentences)",
      metric("text_words")(text_pair(FENCED), {"field": "title"})["value"] == 5
      and metric("text_sentences")(text_pair(FENCED), {"field": "description"})["value"] == 2
      and metric("text_sentences")(text_pair("A mug of 0.35 l, in red"), {})["value"] == 1)
try:
    metric("text_words")(text_pair("no json here"), {"field": "title"})
    refused = False
except ValueError:
    refused = True
check("text: `field:` on an answer that is not JSON is an error, not a silent pass", refused)
check("text: a fenced JSON answer is valid, says it was fenced, and fails `strict`",
      metric("text_json")(text_pair(FENCED), {"keys": ["title"]}) == {"value": 1.0, "missing": "", "fenced": True}
      and metric("text_json")(text_pair(FENCED), {"keys": ["title"], "strict": True})["value"] == 0.0)
check("text: reasoning left in the answer is counted, and kept out of the other text checks",
      metric("text_reasoning_leak")(text_pair(THOUGHT), {})["value"] == 8
      and metric("text_reasoning_leak")(text_pair(FENCED), {})["value"] == 0
      and metric("text_words")(text_pair(THOUGHT), {})["value"] == 3
      and metric("text_json")(text_pair(THOUGHT), {"strict": True})["value"] == 0.0
      and metric("text_json")(text_pair(THOUGHT), {})["value"] == 1.0)


def outline_pair(m, ref=None):
    return SimpleNamespace(out_is_outline=True, m_out=m, region=lambda spec=None, side="in": ref)


box = np.zeros((200, 200), bool)
box[40:120, 50:150] = True
disc = np.hypot(*(np.mgrid[0:200, 0:200] - 100)) < 60
two = box.copy()
two[150:180, 20:60] = True
ref = np.zeros((200, 200), bool)
ref[20:140, 30:170] = True
check("mask: a rectangle fills its box, a traced shape does not",
      metric("mask_box_fill")(outline_pair(box), {})["value"] == 1.0
      and 0.7 < metric("mask_box_fill")(outline_pair(disc), {})["value"] < 0.85)
check("mask: pieces, coverage and placement are read without a matching outline",
      metric("mask_pieces")(outline_pair(box), {})["value"] == 1 and metric("mask_pieces")(outline_pair(two), {})["value"] == 2
      and metric("mask_pieces")(outline_pair(np.zeros((200, 200), bool)), {})["value"] == 0
      and metric("mask_selected_share")(outline_pair(box), {})["value"] == 0.2
      and metric("mask_inside")(outline_pair(box, ref), {})["value"] == 1.0
      and metric("mask_inside")(outline_pair(two, ref), {})["value"] < 0.9)

tmp = tempfile.mkdtemp()
solid = np.zeros((200, 200, 4), np.uint8)
solid[..., :3] = 120
solid[40:160, 40:160, 3] = 255
faint = solid.copy()
faint[40:160, 40:160, 3] = 235
for name, arr in (("solid", solid), ("faint", faint)):
    _Image.fromarray(arr, "RGBA").save(os.path.join(tmp, name + ".png"))
inside = np.zeros((200, 200), bool)
inside[40:160, 40:160] = True
alpha_pair = lambda name: SimpleNamespace(alpha_file=os.path.join(tmp, name + ".png"), W=200, H=200,
                                          region=lambda spec=None, side="in": inside)
check("cut-out: a subject left faintly see-through is caught by opacity, and is not called a soft edge",
      metric("alpha_opacity")(alpha_pair("solid"), {})["value"] == 1.0
      and metric("alpha_opacity")(alpha_pair("faint"), {})["value"] < 0.93
      and metric("alpha_edge_softness")(alpha_pair("faint"), {})["value"] < 12)

rng = np.random.default_rng(3)
truth = cv2.GaussianBlur((rng.random((256, 256, 3)) * 255).astype(np.uint8), (0, 0), 1.2)
small = cv2.resize(truth, (128, 128), interpolation=cv2.INTER_AREA)
noisy = np.clip(cv2.resize(small, (256, 256), interpolation=cv2.INTER_CUBIC).astype(int)
                + rng.integers(-60, 60, (256, 256, 3)), 0, 255).astype(np.uint8)
for name, arr in (("truth", truth), ("exact", truth), ("noisy", noisy)):
    _Image.fromarray(arr).save(os.path.join(tmp, name + ".png"))
up_pair = lambda name, **inp: SimpleNamespace(
    input=inp, bench={"_dir": tmp}, out_file=os.path.join(tmp, name + ".png"), rgb_in=small / 255.0, W=128, H=128,
    native=(256, 256), text=None, svg=None, mesh=None, video=None, region=lambda spec=None, side="in": np.ones((128, 128), bool))
exact = metric("upscale_truth_ssim")(up_pair("exact", original="truth.png"), {})
worse = metric("upscale_truth_ssim")(up_pair("noisy", original="truth.png"), {})
check("upscale: against the original, a perfect result scores 1 and invented texture scores below a plain resize",
      exact["value"] > 0.999 and exact["over_plain_resize"] > 0 and worse["over_plain_resize"] < 0
      and metric("upscale_truth_psnr")(up_pair("exact", original="truth.png"), {})["value"] == 99.0
      and metric("upscale_truth_psnr")(up_pair("noisy", original="truth.png"), {})["over_plain_resize"] < 0, f"{exact} {worse}")
try:
    metric("upscale_truth_ssim")(up_pair("exact"), {})
    refused = False
except KeyError:
    refused = True
check("upscale: without an `original:` the ground-truth checks do not run", refused)
check("size kept: a result that came back smaller is reported",
      metric("size_kept")(SimpleNamespace(native=(1536, 2048), W=1920, H=2560, text=None, svg=None, mesh=None, video=None), {})
      == {"value": 0.8, "native": "1536x2048"})

sys.exit(0 if ok else 1)
