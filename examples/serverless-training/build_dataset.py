"""Collates the training pairs from the dataset run: control = the product photo, target = the teacher's relight.
Only the worst offenders are left out (see RULES). Writes dataset/{control,target}/<name>.jpg at 1024 px,
dataset/metadata.jsonl (for `datasets` imagefolder: columns image, control, prompt), dataset/rejected.json and
dataset.zip.      ../runware-eval/runner/.venv/Scripts/python build_dataset.py"""
import json, os, shutil, zipfile
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RUN, OUT, SIDE = os.path.join(HERE, "runs", "dataset"), os.path.join(HERE, "dataset"), 1024
# Left out: the backdrop turned dark; no shadow to the right (it fell under or onto the product); the product
# changed shape or moved; the judges said it is not the same product.
RULES = {"backdrop turned dark": lambda v, m: v("Background lightness") < -10,
         "no shadow to the right": lambda v, m: v("Shadow to the right") < 3,
         "product changed shape or moved": lambda v, m: v("Outline") < 0.90 or v("Shift (px)") > 20,
         "judges: not the same product": lambda v, m: m["Same product (judges)"].get("pass") is False}
# One schema, several wordings (BFL's guide: 5 to 10 phrasings help an edit LoRA generalise).
PROMPTS = [
    "Relight this product photo with one hard key light from the upper left: bright left and top surfaces, deep shadow on the right side, and a dark, well-defined shadow cast to the right. Keep the product, the white background and the framing exactly the same.",
    "Change only the lighting: a single hard light from the upper left, high contrast, crisp shadow edge, the product's shadow falling to the right. Same product, same white background.",
    "Apply hard studio light from the upper left to this product. The right side goes into deep shadow and a dark cast shadow falls to the right. Do not change the product or the background.",
    "Relight with a hard key light coming from the upper left and very little fill. Strong contrast, well-defined cast shadow to the right of the product. Everything else stays as it is.",
    "Hard light from the upper left, deep shadows to the right, high contrast. Keep the same product in the same place on the same white background.",
    "Light this product with one hard, directional light from the upper left so that its right side is in shadow and it casts a dark shadow to the right. Keep shape, colours, details, background and framing unchanged.",
]

scores = json.load(open(os.path.join(RUN, "scores.json"), encoding="utf8"))
if os.path.isdir(OUT):
    shutil.rmtree(OUT)
for d in ("control", "target"):
    os.makedirs(os.path.join(OUT, d))
kept, rejected = [], []
for s in sorted(scores["scored"], key=lambda s: (s["input"], s["seed"])):
    m = {x["label"]: x for x in s["metrics"]}
    v = lambda label: (m[label].get("values") or {}).get("value", float("nan"))
    why = [name for name, rule in RULES.items() if rule(v, m)]
    name = f"{s['input']}__{s['seed']}"
    if why:
        rejected.append({"pair": name, "why": why})
        continue
    for folder, src in (("control", os.path.join(HERE, "inputs", "products", s["input"] + ".jpg")), ("target", os.path.join(RUN, s["file"]))):
        Image.open(src).convert("RGB").resize((SIDE, SIDE), Image.LANCZOS).save(os.path.join(OUT, folder, name + ".jpg"), quality=92)
    kept.append({"file_name": f"target/{name}.jpg", "control_file_name": f"control/{name}.jpg", "prompt": PROMPTS[len(kept) % len(PROMPTS)]})
with open(os.path.join(OUT, "metadata.jsonl"), "w", encoding="utf8") as f:
    f.write("".join(json.dumps(k) + "\n" for k in kept))
json.dump(rejected, open(os.path.join(OUT, "rejected.json"), "w"), indent=1)
with zipfile.ZipFile(os.path.join(HERE, "dataset.zip"), "w", zipfile.ZIP_STORED) as z:
    for root, _, files in os.walk(OUT):
        for fn in files:
            if fn != "rejected.json":
                z.write(os.path.join(root, fn), os.path.relpath(os.path.join(root, fn), OUT))
per = {}
for k in kept:
    per[k["file_name"].split("/")[1].split("__")[0]] = per.get(k["file_name"].split("/")[1].split("__")[0], 0) + 1
print(f"{len(kept)} pairs kept over {len(per)} products, {len(rejected)} left out; dataset.zip {os.path.getsize(os.path.join(HERE, 'dataset.zip')) / 1e6:.1f} MB")
print("pairs per product:", sorted(per.values()))
for r in rejected:
    print("  out:", r["pair"], "-", "; ".join(r["why"]))
