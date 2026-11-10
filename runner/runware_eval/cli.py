"""runware-eval estimate | run | score | report <bench.yaml>"""
import argparse
import json
import os
import sys

from . import api, bench, report, run, score


def common(ap):
    ap.add_argument("bench", help="path to bench.yaml")
    ap.add_argument("--out", help="output folder (default: <bench dir>/runs/<round>)")
    ap.add_argument("--round", choices=["smoke", "full"], default="smoke",
                    help="smoke: first input, first seed. full: everything (default: smoke)")
    ap.add_argument("--inputs", nargs="*", help="only these inputs (file stems)")
    ap.add_argument("--recipes", nargs="*", help="only these recipe ids")


def setup(a):
    b = bench.load(a.bench)
    out = a.out or os.path.join(b["_dir"], "runs", a.round)
    os.makedirs(out, exist_ok=True)
    return b, out


def brief_coverage(b):
    """Say, before anything is paid, which parts of the brief no check covers."""
    _, warn = score.coverage(b)
    if warn:
        print("Brief coverage:")
        for w in warn:
            print("  ! " + w)
        print()


def cmd_estimate(a):
    b, out = setup(a)
    bench.ensure_media(b, os.path.join(out, "media.lock.json"))
    run.ensure_input_masks(b, out)
    run.ensure_recipe_masks(b, out, os.path.join(out, "media.lock.json"))
    jobs = bench.jobs(b, a.round, a.inputs, a.recipes)
    runs_root = os.path.join(b["_dir"], "runs")
    past = [r for d in (os.listdir(runs_root) if os.path.isdir(runs_root) else [])
            for r in run.read_results(os.path.join(runs_root, d))]
    rows = run.estimate(jobs, run.read_results(out) + past)
    total = sum(r["est_cost"] or 0 for r in rows)
    by = {}
    for r in rows:
        x = by.setdefault(r["recipe"], {"n": 0, "cost": r["est_cost"], "src": r["est_source"]})
        x["n"] += 1
    brief_coverage(b)
    print(f"{'recipe':34} {'tasks':>5} {'$/task':>9}  source")
    for rid, x in by.items():
        c = f"{x['cost']:.4f}" if x["cost"] is not None else "?"
        print(f"{rid:34} {x['n']:>5} {c:>9}  {x['src']}")
    cap = bench.maxSpend(b)
    print(f"\n{len(rows)} tasks, about ${total:.3f}" + (f" (cap ${cap:.2f})" if cap else "")
          + ". Masks for scoring add a small amount per output.")
    print("Measured costs come from earlier runs of this bench; otherwise the recipe's own price note, else the "
          "model's highest listed price. Runware has no reliable dry-run, so a smoke round is the way to measure.")


def cmd_run(a):
    b, out = setup(a)
    cap = bench.maxSpend(b)
    if cap is None:
        sys.exit("bench.yaml has no budget.maxSpend: set a cap before running.")
    brief_coverage(b)
    bench.ensure_media(b, os.path.join(out, "media.lock.json"))
    run.ensure_input_masks(b, out)
    run.ensure_recipe_masks(b, out, os.path.join(out, "media.lock.json"))
    jobs = bench.jobs(b, a.round, a.inputs, a.recipes)
    runs_root = os.path.join(b["_dir"], "runs")
    hist = [os.path.join(runs_root, d) for d in os.listdir(runs_root)] if os.path.isdir(runs_root) else []
    results = run.execute(jobs, out, cap, history_dirs=hist + (a.history or []), b=b,
                          lock_path=os.path.join(out, "media.lock.json"))
    print(f"Done. Results in {out}")
    if not a.no_score:
        cmd_score(a, b, out, results)


def cmd_score(a, b=None, out=None, results=None):
    if b is None:
        b, out = setup(a)
        run.prepare_offline(b, out)
    data = score.score_all(b, out, results if results is not None else run.read_results(out),
                           judges=not getattr(a, "no_judges", False),
                           maxSpend=bench.maxSpend(b))
    print(f"Scored {len(data['scored'])} outputs → {os.path.join(out, 'scores.json')}")
    cmd_report(a, b, out)


def cmd_report(a, b=None, out=None):
    if b is None:
        b, out = setup(a)
        run.prepare_offline(b, out)
    notes = json.load(open(a.notes, encoding="utf8")) if getattr(a, "notes", None) else None
    listed = {r["id"]: api.recipe_price(r) for r in b["recipes"]}
    print("Report →", report.build(b, out, notes, listed))


def cmd_label(a):
    from . import label
    b, out = setup(a)
    path, n, p = label.build(b, out, pairs_per_recipe=a.pairs_per_recipe)
    print(f"Labeling page: {path}  ({n} outputs, {p} pairs, blind and shuffled)")
    print("Open it, label what you can, press 'Download labels.json', then run:")
    print(f"  runware-eval calibrate {a.bench} --round {a.round} --labels <path to labels.json>")


def cmd_calibrate(a):
    from . import calibrate
    b, out = setup(a)
    calibrate.run(out, a.labels)
    run.prepare_offline(b, out)
    cmd_report(a, b, out)


def cmd_metrics(a):
    from . import catalog
    b = bench.load(a.bench)
    reg = catalog.load(b)
    if a.action == "markdown":
        print(catalog.markdown(reg))
        return
    if a.action == "list":
        print(f"{'id':22} {'kind':9} {'family':13} {'source':10} fingerprint")
        for mid, m in sorted(reg.items(), key=lambda x: (x[1]["source"] != "bench", x[0])):
            over = f"  (overrides {', '.join(m['overrides'])})" if m.get("overrides") else ""
            print(f"{mid:22} {m['meta']['kind']:9} {m['meta']['family']:13} {m['source']:10} {m['fp']}{over}")
        return
    out = os.path.join(b["_dir"], "runs", "_controls")
    os.makedirs(out, exist_ok=True)
    run.prepare_offline(b, out)
    from .score import controls
    rows = controls(b, reg)
    for c in rows:
        mark = "ok  " if c["ok"] else "FAIL"
        want = "pass" if c["expected_pass"] else "fail"
        got = "passed" if c["passed"] else "failed"
        print(f"{mark} {c['input']:16} {c['label']:30} {c['kind']:8} value {c['value']:.4g} {got} (should {want})")
    print(f"{sum(c['ok'] for c in rows)}/{len(rows)} controls as expected.")


def cmd_recipes(a):
    from . import recipes as rec
    if a.action == "extract":
        b = bench.load(a.bench, resolve_recipes=False)
        written = rec.extract(b, a.bench)
        print("\n".join(f"wrote {w}" for w in written) or "No inline recipes to extract.")
        if written:
            print(f"bench.yaml now lists them by id (backup: {a.bench}.pre-extract.bak)")
        return
    b = bench.load(a.bench)
    runs_root = os.path.join(b["_dir"], "runs")
    seen = {}
    if os.path.isdir(runs_root):
        for d in os.listdir(runs_root):
            for r in run.read_results(os.path.join(runs_root, d)):
                if r.get("status") == "success" and r.get("fp"):
                    seen[r["fp"]] = seen.get(r["fp"], 0) + 1
    print(f"{'id':36} {'fingerprint':17} {'runs':>4}  model")
    for r in b["recipes"]:
        flag = "  (edited: new fingerprint)" if r.get("_edited_from") else ""
        print(f"{r['id']:36} {r['_fp']:17} {seen.get(r['_fp'], 0):>4}  {r['model']}{flag}")


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="runware-eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("estimate", cmd_estimate), ("run", cmd_run), ("score", cmd_score), ("report", cmd_report)):
        p = sub.add_parser(name)
        common(p)
        p.add_argument("--notes", help="JSON with `findings` and `caveats` to show in the report")
        if name == "run":
            p.add_argument("--no-score", action="store_true")
            p.add_argument("--history", nargs="*", help="extra run folders to reuse matching results from")
        if name in ("run", "score"):
            p.add_argument("--no-judges", action="store_true", help="skip the vision-model checks")
        p.set_defaults(fn=fn)
    lp = sub.add_parser("label", help="make a blind labeling page (good/bad and pairwise) for a scored run")
    common(lp)
    lp.add_argument("--pairs-per-recipe", type=int, default=4)
    lp.set_defaults(fn=cmd_label)
    cp = sub.add_parser("calibrate", help="read labels.json: agreement per check, suggested thresholds, human ranking")
    common(cp)
    cp.add_argument("--labels", required=True, help="the labels.json downloaded from the labeling page")
    cp.add_argument("--notes")
    cp.set_defaults(fn=cmd_calibrate)
    mp = sub.add_parser("metrics", help="list metrics (library + bench), run the controls, or print the registry")
    mp.add_argument("action", choices=["list", "control", "markdown"])
    mp.add_argument("bench")
    mp.set_defaults(fn=cmd_metrics)
    rp = sub.add_parser("recipes", help="list recipe files, or extract inline recipes into files")
    rp.add_argument("action", choices=["list", "extract"])
    rp.add_argument("bench")
    rp.set_defaults(fn=cmd_recipes)
    a = ap.parse_args()
    try:
        a.fn(a)
    except (api.RunwareError, ValueError, FileExistsError, KeyError) as err:
        sys.exit(f"runware-eval: {err}")


if __name__ == "__main__":
    main()
