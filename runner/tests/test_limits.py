"""Limits for numeric checks, set from a run's results and frozen in limits.yaml."""
import os
import sys
import tempfile

import yaml

from runware_eval import catalog, limits, score

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


def bench(d, extra=None):
    return {"_dir": d, "evaluate": {
        "deviation": {"metrics": [{"id": "deltaE2000_region", "region": "product", "label": "Hue", **(extra or {})}]},
        "pixel_shift": {"metrics": [{"id": "phase_correlation", "label": "Shift"},
                                     {"id": "mask_iou", "region": "product", "label": "Outline"},
                                     {"id": "mesh_faces", "label": "Faces"}]},
        "prompt_adherence": {"metrics": [{"id": "vlm_checklist", "label": "Real", "questions": ["q"]}]}}}


def scored(values):
    """values: {label: {recipe: [draws]}}"""
    out = {}
    for lab, per in values.items():
        for rid, vs in per.items():
            for n, v in enumerate(vs, 1):
                out.setdefault((rid, n), {"recipe": rid, "input": "a", "seed": n, "metrics": []})["metrics"].append(
                    {"label": lab, "status": "ok", "values": {"value": v}})
    return list(out.values())


reg = catalog.load()
V = {"Hue": {"lazy": [2.9, 2.9, 2.9], "flux": [9.4, 7.5, 7.1], "nano": [4.1, 6.1, 5.7], "seed": [5.2, 5.2, 4.8]},
     "Shift": {"lazy": [0.13] * 3, "flux": [0.9, 0.88, 0.8], "nano": [0.47, 0.5, 0.4], "seed": [0.2, 0.2, 0.25]},
     "Outline": {"lazy": [0.98] * 3, "flux": [0.97, 0.98, 0.93], "nano": [0.99, 0.98, 0.98], "seed": [0.98, 0.99, 0.98]},
     "Faces": {"lazy": [100] * 3, "flux": [200] * 3, "nano": [300] * 3, "seed": [400] * 3},
     "Real": {"lazy": [1.0] * 3, "flux": [1.0] * 3, "nano": [1.0] * 3, "seed": [1.0] * 3}}
tmp = tempfile.mkdtemp()
b = bench(tmp)
got = limits.propose(b, scored(V), reg)
check("a 'lower is better' check gets a max: median of the recipes' medians plus the draw spread",
      abs(got["Hue"]["max"] - (5.45 + 2.0)) < 0.01 or abs(got["Hue"]["max"] - 6.65) < 0.3, got.get("Hue"))
check("one recipe that changed nothing does not pull the limit down", got["Hue"]["max"] > 6.0)
check("where every recipe is close, the margin is the metric's smallest difference (2 px)",
      abs(got["Shift"]["max"] - (0.335 + 2)) < 0.05, got.get("Shift"))
check("a 'higher is better' check gets a min", "min" in got["Outline"] and abs(got["Outline"]["min"] - 0.96) < 0.01, got.get("Outline"))
check("the origin is written out in words", "median of 4 recipes" in got["Hue"]["from"] and "spread between draws" in got["Hue"]["from"])
check("a metric with no direction gets no limit", "Faces" not in got)
check("a yes/no judge check gets none: it passes or fails by itself", "Real" not in got)
check("fewer than two recipes: no limit", limits.propose(b, scored({"Hue": {"seed": [5, 5, 5]}}), reg) == {})
check("a limit written in bench.yaml is left alone", "Hue" not in limits.propose(bench(tmp, {"mean_max": 6.5}), scored(V), reg))
check("`limit: none` keeps a check measured only", "Hue" not in limits.propose(bench(tmp, {"limit": "none"}), scored(V), reg))

added = limits.freeze(b, got, "full")
check("the limits are written to limits.yaml", set(added) == {"Hue", "Shift", "Outline"} and os.path.exists(limits.path(b)))
first = yaml.safe_load(open(limits.path(b), encoding="utf8"))["Hue"]["max"]
b2 = bench(tmp)
check("the next load puts them on the checks", limits.attach(b2) == 3
      and b2["evaluate"]["deviation"]["metrics"][0]["max"] == first and b2["evaluate"]["deviation"]["metrics"][0]["limitFrom"])
check("a check with a frozen limit is pass/fail and counts as a limit for its requirement",
      score.row_mode(b2["evaluate"]["deviation"]["metrics"][0]) == "gate"
      and score.check({"value": first + 1}, b2["evaluate"]["deviation"]["metrics"][0]) is False
      and score.check({"value": first - 1}, b2["evaluate"]["deviation"]["metrics"][0]) is True)
worse = {**V, "Hue": {k: [x * 3 for x in v] for k, v in V["Hue"].items()}}
check("frozen: other results later do not move a limit",
      limits.propose(b2, scored(worse), reg) == {} and limits.freeze(b2, limits.propose(bench(tmp), scored(worse), reg), "full") == {}
      and yaml.safe_load(open(limits.path(b), encoding="utf8"))["Hue"]["max"] == first)
b3 = bench(tmp, {"mean_max": 3.0})
limits.attach(b3)
check("bench.yaml's own limit wins over limits.yaml", "max" not in b3["evaluate"]["deviation"]["metrics"][0])
check("the report can list them with their origin", [r[0] for r in limits.listed(b2)] == ["Hue", "Shift", "Outline"]
      and limits.listed(b2)[0][1].startswith("at most"))
one = {"Shift": {"a": [0.2], "b": [0.4], "c": [5.0]}}
got1 = limits.propose(bench(tempfile.mkdtemp()), scored(one), reg)
check("one draw per recipe: the margin is the smallest difference alone", abs(got1["Shift"]["max"] - 2.4) < 0.01, got1)

# the run that sets the limits is judged against them without being measured again
d4 = tempfile.mkdtemp()
b4 = {**bench(d4), "inputs": []}
rows4 = scored(V)
for s_ in rows4:
    for m in s_["metrics"]:
        m.update(mode="rank", thresholds={}, id="x")
limits.freeze(b4, limits.propose(b4, rows4, reg), "full")
limits.attach(b4)
data4 = score.recheck(b4, {"scored": rows4}, d4)
hue = {(s_["recipe"], s_["seed"]): m for s_ in data4["scored"] for m in s_["metrics"] if m["label"] == "Hue"}
lim4 = b4["evaluate"]["deviation"]["metrics"][0]["max"]
check("after the limits are set, the same values get their pass or fail (nothing is measured twice)",
      hue[("flux", 1)]["pass"] is False and hue[("lazy", 1)]["pass"] is True and hue[("flux", 1)]["mode"] == "gate"
      and hue[("flux", 1)]["thresholds"].get("max") == lim4 and os.path.exists(os.path.join(d4, "scores.json")))
faces = [m for s_ in data4["scored"] for m in s_["metrics"] if m["label"] == "Faces"]
check("a check that got no limit stays measured only", all(m["mode"] == "rank" and m.get("pass") is None for m in faces))

# a metric with a natural "nothing happened" states its own limit: the other recipes do not move it
b5 = {"_dir": tempfile.mkdtemp(), "evaluate": {"motion": {"metrics": [{"id": "video_motion", "label": "Motion"}]}}}
own = limits.propose(b5, scored({"Motion": {"still": [0.1], "slow": [1.3], "fast": [2.9]}}), reg)
check("video_motion gets its own limit, not the median of the recipes",
      own.get("Motion", {}).get("min") == 0.5 and "own limit" in own["Motion"]["from"], own)

# a limit is rounded towards "worse", so a recipe sitting exactly on it never fails by rounding
check("a floor is rounded down and a ceiling up",
      limits._round(1.6406002, "higher") == 1.640 and limits._round(1.6406002, "lower") == 1.641
      and limits._round(0.25, "higher") == 0.25 and limits._round(0.0, "lower") == 0.0
      and limits._round(-1.23456, "higher") <= -1.23456 <= limits._round(-1.23456, "lower"))

print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
sys.exit(1 if FAILED else 0)
