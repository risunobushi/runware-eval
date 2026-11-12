"""The report computes calibration in the page (JavaScript); `runware-eval calibrate` computes it in
Python. This runs both on the same random scores and labels and checks they agree.

Needs Node.js for the JavaScript side; without it the test is skipped.
Run: uv run --project runner python runner/tests/test_labeling_js.py
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

from runware_eval import _labeling, calibrate

from harness import check, finish

node = shutil.which("node")
if not node:
    print("SKIPPED: Node.js not found")
    sys.exit(0)

rng = random.Random(5)
recipes = [f"r{i}" for i in range(6)]
CHECKS = [("deviation", "Colour", "gate", {"mean_max": 3.0, "p95_max": 6.0}), ("shift", "Outline", "gate", {"min": 0.95}),
          ("deviation", "Backdrop light", "gate", {"abs_max": 10}), ("adherence", "Key light", "gate", {"min": 3.0}),
          ("quality", "Sharpness", "rank", {}), ("quality", "Structure", "rank", {})]
scored = []
for inp in ("a", "b", "c"):
    for r in recipes:
        for seed in (1, 2):
            ms = []
            for dim, lab, mode, th in CHECKS:
                v = rng.uniform(-12, 12) if lab == "Backdrop light" else rng.uniform(0, 8) if "max" in str(th) else rng.uniform(0, 5)
                vals = {"value": v}
                if lab == "Colour":
                    vals.update(mean=v, p95=v * 1.8)
                if lab == "Structure" and rng.random() < 0.1:
                    vals["value"] = float("nan")
                passed = None
                if mode == "gate":
                    passed = (abs(v) <= th["abs_max"] if "abs_max" in th else v >= th["min"] if "min" in th
                              else v <= th["mean_max"] and v * 1.8 <= th["p95_max"])
                status = "ok" if rng.random() > 0.05 else "not_run"
                ms.append({"dimension": dim, "label": lab, "mode": mode, "status": status, "pass": passed,
                           "values": vals, "thresholds": th})
            scored.append({"file": f"{inp}__{r}__s{seed}.jpg", "input": inp, "recipe": r, "seed": seed, "metrics": ms})

files = [s["file"] for s in scored]
labels = {f: rng.choice(["good", "good", "bad"]) for f in rng.sample(files, 26)}
labels["not_in_this_run.jpg"] = "good"
pairs = []
for _ in range(30):
    a, b = rng.sample(files, 2)
    pairs.append({"a": a, "b": b, "winner": rng.choice(["a", "b", "a", "b", "tie"])})

d = tempfile.mkdtemp()
json.dump({"scored": scored}, open(os.path.join(d, "scores.json"), "w"))
json.dump({"labels": labels, "pairs": pairs}, open(os.path.join(d, "in.json"), "w"))
py = calibrate.run(d, os.path.join(d, "in.json"), log=lambda *a: None)

cal, _ = _labeling.data(scored, {}, "t", "run")
js = _labeling.JS
pure = js[js.index("// CAL-BEGIN"):js.index("// CAL-END")]
script = pure + "\nconst inp = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));\n" \
                "console.log(JSON.stringify(calibrate(inp.cal, inp.labels, inp.pairs)));\n"
json.dump({"cal": cal, "labels": labels, "pairs": pairs}, open(os.path.join(d, "js_in.json"), "w"))
open(os.path.join(d, "cal.js"), "w", encoding="utf8").write(script)
res = subprocess.run([node, os.path.join(d, "cal.js"), os.path.join(d, "js_in.json")], capture_output=True, text=True)
if res.returncode:
    print("FAIL node:", res.stderr[:600])
    sys.exit(1)
jsr = json.loads(res.stdout)



def close(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= 1e-6 * max(1, abs(a))


check("labeled and good counts", (py["labeled"], py["good"], py["few_labels"]) == (jsr["labeled"], jsr["good"], jsr["few_labels"]),
      f"{py['labeled']} labeled, {py['good']} good")
check("same gates, in the same order", [g["label"] for g in py["gates"]] == [g["label"] for g in jsr["gates"]],
      str([g["label"] for g in py["gates"]]))
check("gate agreement and suggested thresholds match", all(
    g["key"] == h["key"] and g["n"] == h["n"] and close(g["agreement_now"], h["agreement_now"])
    and close(g["suggested"], h["suggested"]) and close(g["agreement_suggested"], h["agreement_suggested"])
    for g, h in zip(py["gates"], jsr["gates"])))
check("rank metrics (AUC) match", len(py["ranks"]) == len(jsr["ranks"]) and all(
    a["label"] == b["label"] and a["n"] == b["n"] and close(a["auc"], b["auc"]) for a, b in zip(py["ranks"], jsr["ranks"])))
check("pairwise ranking matches", set(py["human_ranking"]) == set(jsr["human_ranking"]) and all(
    close(py["human_ranking"][r]["score"], jsr["human_ranking"][r]["score"])
    and close(py["human_ranking"][r]["wins"], jsr["human_ranking"][r]["wins"])
    and close(py["human_ranking"][r]["games"], jsr["human_ranking"][r]["games"]) for r in py["human_ranking"]),
      str({r: round(v["score"], 3) for r, v in sorted(py["human_ranking"].items())}))
open(os.path.join(d, "full.js"), "w", encoding="utf8").write("const D = {};\n" + js)
syn = subprocess.run([node, "--check", os.path.join(d, "full.js")], capture_output=True, text=True)
check("the whole page script parses", syn.returncode == 0, syn.stderr[:300])
finish()
