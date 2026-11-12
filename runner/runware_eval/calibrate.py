"""The user's labels as a second opinion on the limits, and their own ranking of the recipes.

The limits are set elsewhere: from the first full run (limits.yaml), or by the brief (bench.yaml).
This only compares them with the labels the user gave on the labeling page, and changes nothing.

- Checks with a limit: how often pass/fail matched the user's good/bad, and the limit that would
  have matched best (balanced accuracy, so a few "bad" labels still count). A suggestion the user
  accepts is written where the limit lives, by hand.
- Checks without a limit: how well the value orders the user's good above their bad (AUC: 0.5 = chance).
- Pairs: a Bradley-Terry score per recipe from "A is better / B is better / about the same".
Writes calibration.json next to the run; the report shows it.
"""
import json
import os

import numpy as np

LOWER_KEYS = ("max", "mean_max", "p95_max", "max_px", "aspect_tolerance", "dL_max")
HIGHER_KEYS = ("min", "dL_min")


def _direction(thresholds):
    if "abs_max" in thresholds:
        return "abs_lower", "abs_max"
    for k in LOWER_KEYS:
        if k in thresholds:
            return "lower", k
    for k in HIGHER_KEYS:
        if k in thresholds:
            return "higher", k
    return None, None


def _value(m, key):
    v = m.get("values") or {}
    return v.get("mean", v.get("value")) if key == "mean_max" else v.get("p95", v.get("value")) if key == "p95_max" \
        else v.get("value")


def _balanced(pred, good):
    pred, good = np.asarray(pred, bool), np.asarray(good, bool)
    tpr = (pred & good).sum() / max(1, good.sum())
    tnr = (~pred & ~good).sum() / max(1, (~good).sum())
    return float((tpr + tnr) / 2)


def _auc(values, good):
    v, g = np.asarray(values, float), np.asarray(good, bool)
    pos, neg = v[g], v[~g]
    if not len(pos) or not len(neg):
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return float(wins / (len(pos) * len(neg)))


def bradley_terry(pairs, files_to_recipe, iters=200):
    """MM algorithm; ties count as half a win each. Returns {recipe: score (1 = average), wins, games}."""
    recs = sorted(set(files_to_recipe.values()))
    idx = {r: i for i, r in enumerate(recs)}
    w = np.zeros((len(recs), len(recs)))
    for p in pairs:
        a, b = files_to_recipe.get(p["a"]), files_to_recipe.get(p["b"])
        if a is None or b is None or a == b:
            continue
        i, j = idx[a], idx[b]
        if p["winner"] == "a":
            w[i, j] += 1
        elif p["winner"] == "b":
            w[j, i] += 1
        else:
            w[i, j] += 0.5
            w[j, i] += 0.5
    n = w + w.T
    s = np.ones(len(recs))
    # One virtual draw against an average opponent (score 1) per recipe: keeps scores finite for unbeaten
    # or winless records and pulls thin evidence towards the middle.
    for _ in range(iters):
        wins = w.sum(1) + 0.5
        denom = np.array([sum(n[i, j] / (s[i] + s[j]) for j in range(len(recs)) if n[i, j]) + 1 / (s[i] + 1)
                          for i in range(len(recs))])
        s = wins / denom
        s = s / np.exp(np.mean(np.log(s)))  # geometric mean 1
    return {r: {"score": float(s[idx[r]]), "wins": float(w[idx[r]].sum()), "games": float(n[idx[r]].sum())}
            for r in recs if n[idx[r]].sum()}


def run(out_dir, labels_path, log=print):
    labels = json.load(open(labels_path, encoding="utf8"))
    json.dump(labels, open(os.path.join(out_dir, "labels.json"), "w", encoding="utf8"), indent=1)
    data = json.load(open(os.path.join(out_dir, "scores.json"), encoding="utf8"))
    by_file = {s["file"]: s for s in data["scored"]}
    lab = {f: v == "good" for f, v in labels.get("labels", {}).items() if f in by_file}
    out = {"labeled": len(lab), "good": int(sum(lab.values())), "gates": [], "ranks": [], "human_ranking": {}}

    rows = {}
    for f, good in lab.items():
        for m in by_file[f]["metrics"]:
            if m.get("status") == "ok":
                rows.setdefault((m["dimension"], m["label"], m["mode"]), []).append((f, m, good))
    for (dim, lbl, mode), xs in sorted(rows.items()):
        good = [g for _, _, g in xs]
        if mode == "gate":
            direction, key = _direction(xs[0][1].get("thresholds") or {})
            passes = [m.get("pass") for _, m, _ in xs]
            if direction is None or None in passes:
                continue
            vals = [_value(m, key) for _, m, _ in xs]
            vals = [abs(v) for v in vals] if direction == "abs_lower" else vals
            now = _balanced(passes, good)
            best = (now, (xs[0][1]["thresholds"] or {}).get(key))
            cand = sorted(set(v for v in vals if v is not None and not np.isnan(v)))
            for lo, hi in zip(cand, cand[1:]):
                t = (lo + hi) / 2
                pred = [(v <= t) if direction in ("lower", "abs_lower") else (v >= t) for v in vals]
                score = _balanced(pred, good)
                if score > best[0] + 1e-9:
                    best = (score, round(t, 4))
            out["gates"].append({"dimension": dim, "label": lbl, "key": key, "n": len(xs),
                                 "threshold_now": (xs[0][1]["thresholds"] or {}).get(key), "agreement_now": now,
                                 "suggested": best[1], "agreement_suggested": best[0]})
        else:
            vals = [(m.get("values") or {}).get("value") for _, m, _ in xs]
            ok = [(v, g) for v, g in zip(vals, good) if v is not None and not np.isnan(v)]
            auc = _auc([v for v, _ in ok], [g for _, g in ok]) if ok else None
            if auc is not None:
                out["ranks"].append({"dimension": dim, "label": lbl, "n": len(ok), "auc": auc})

    files_to_recipe = {f: s["recipe"] for f, s in by_file.items()}
    if labels.get("pairs"):
        out["human_ranking"] = bradley_terry(labels["pairs"], files_to_recipe)
    out["few_labels"] = out["labeled"] < 20 or min(out["good"], out["labeled"] - out["good"]) < 5
    json.dump(out, open(os.path.join(out_dir, "calibration.json"), "w", encoding="utf8"), indent=1)

    log(f"{out['labeled']} outputs labeled ({out['good']} good), {len(labels.get('pairs', []))} pairs.")
    if out["few_labels"]:
        log("Few labels (or few of one kind): treat suggested limits as hints, not answers. "
            "About 20 labels with at least 5 good and 5 bad make them dependable.")
    if out["gates"]:
        log("\nLimits vs your labels (balanced agreement: 0.5 = chance, 1.0 = always agrees):")
        for g in out["gates"]:
            sug = (f" -> {g['key']}: {g['suggested']} would agree {g['agreement_suggested']:.0%}"
                   if g["suggested"] != g["threshold_now"] else " (no other limit would agree better)")
            log(f"  {g['label']:30} {g['agreement_now']:.0%} with {g['key']}: {g['threshold_now']}{sug}")
    if out["ranks"]:
        log("\nChecks without a limit vs your labels (AUC: 0.5 = no better than chance):")
        for r in out["ranks"]:
            flag = "  <- weak, go by your own ranking" if r["auc"] < 0.7 else ""
            log(f"  {r['label']:30} AUC {r['auc']:.2f} on {r['n']} outputs{flag}")
    if out["human_ranking"]:
        log("\nYour ranking (Bradley-Terry, 1.0 = average):")
        for rid, v in sorted(out["human_ranking"].items(), key=lambda x: -x[1]["score"]):
            log(f"  {rid:34} {v['score']:.2f}  ({v['wins']:g} wins in {v['games']:g})")
    log("\nNothing was changed: labels are a second opinion on the limits, not a new source of them. "
        "To accept a suggestion, edit the limit where it lives (limits.yaml; bench.yaml if the brief "
        "stated it), say in its `from` line that you set it from your labels, and run `score`.")
    return out
