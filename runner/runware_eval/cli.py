"""runware-eval estimate | run | score | report <bench.yaml>"""
import argparse
import json
import os
import sys

from . import api, bench, models, report, run, score


def common(ap):
    ap.add_argument("bench", help="path to bench.yaml")
    ap.add_argument("--out", help="output folder (default: <bench dir>/runs/<round>)")
    ap.add_argument("--round", choices=["smoke", "full"], default="smoke",
                    help="smoke: first input, first draw. full: everything (default: smoke)")
    ap.add_argument("--inputs", nargs="*", help="only these inputs (file stems)")
    ap.add_argument("--recipes", nargs="*", help="only these recipe ids")


def setup(a):
    b = bench.load(a.bench)
    out = a.out or os.path.join(b["_dir"], "runs", a.round)
    os.makedirs(out, exist_ok=True)
    return b, out


def brief_coverage(b, paying=False):
    """Say, before anything is paid, which parts of the brief no check covers. A requirement with no
    check at all stops a paid run: every requirement gets a metric, or is left out by the user's choice."""
    _, warn = score.coverage(b)
    errors = score.coverage_errors(b)
    if warn:
        print("Brief coverage:")
        for w in warn:
            print(("  x " if w in errors else "  ! ") + w)
        print()
    if errors and paying:
        sys.exit("Stopped before spending: a requirement of the brief has no check. Give it a metric (write one in "
                 "metrics/ if the library has none, or a yes/no question for the judges), or, if the user chose not "
                 "to measure it, say so in bench.yaml: `notMeasured: <why>` on that requirement.")


def run_dirs(b):
    root = os.path.join(b["_dir"], "runs")
    return [os.path.join(root, d) for d in os.listdir(root)] if os.path.isdir(root) else []


def model_checks(a, b, out, jobs, paying):
    """Before anything is paid: each recipe's request against its model's published schema, and each
    model's published details against what earlier runs of this bench recorded. Returns {model: fingerprint}."""
    if getattr(a, "skip_model_check", False):
        return {}
    problems, unchecked = models.check_jobs(jobs, b)
    if problems:
        print("Parameter check (each recipe's request against its model's schema):")
        for rid, p in problems.items():
            for line in p["stop"]:
                print(f"  x {rid}: {line}")
            for line in p["warn"]:
                print(f"  ! {rid}: {line} (the schema's rule; the API may still accept it)")
        print()
    if unchecked:
        print(f"Parameters not checked (no published schema found): {', '.join(unchecked)}\n")
    stops = [rid for rid, p in problems.items() if p["stop"]]
    if stops and paying:
        sys.exit(f"Stopped before spending: {', '.join(stops)} send{'s' if len(stops) == 1 else ''} something the model's "
                 "schema does not allow. Runware runs and bills a request with an unknown field, at the model's default. "
                 "Fix the recipe file, or pass --skip-model-check if the schema is wrong.")
    airs = {j["task"]["model"] for j in jobs} | {j["_recipe"]["then"]["model"] for j in jobs if (j.get("_recipe") or {}).get("then")}
    today, changed = models.changes(airs, run_dirs(b))
    if changed:
        print("Models that changed since this bench last ran:")
        for air, c in changed.items():
            print(f"  ! {air} (last recorded {c['since']})")
            for w in c["what"][:8]:
                print(f"      {w}")
            if len(c["what"]) > 8:
                print(f"      and {len(c['what']) - 8} more (see models.json in the run folder)")
        print()
    if paying:
        models.record(out, today, changed)
        old = models.stale([r for r in run.read_results(out) if r.get("status") == "success"], out)
        wanted = {j["hash"] for j in jobs}
        n = sum(h in wanted for h in old)
        if n and not getattr(a, "regenerate_changed", False):
            print(f"{n} cached result(s) in this run were generated before their model changed. They are kept and "
                  "marked in the report; `--regenerate-changed` makes them again (paid).\n")
    return {air: s["fp"] for air, s in today.items()}


def cmd_estimate(a):
    b, out = setup(a)
    bench.ensure_media(b, os.path.join(out, "media.lock.json"))
    run.ensure_input_masks(b, out)
    run.ensure_recipe_masks(b, out, os.path.join(out, "media.lock.json"))
    jobs = bench.jobs(b, a.round, a.inputs, a.recipes)
    past = [r for d in run_dirs(b) for r in run.read_results(d)]
    rows = run.estimate(jobs, run.read_results(out) + past)
    total = sum(r["est_cost"] or 0 for r in rows)
    by = {}
    for r in rows:
        x = by.setdefault(r["recipe"], {"n": 0, "cost": r["est_cost"], "src": r["est_source"]})
        x["n"] += 1
    brief_coverage(b)
    model_checks(a, b, out, jobs, paying=False)
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
    brief_coverage(b, paying=True)
    bench.ensure_media(b, os.path.join(out, "media.lock.json"))
    run.ensure_input_masks(b, out)
    run.ensure_recipe_masks(b, out, os.path.join(out, "media.lock.json"))
    jobs = bench.jobs(b, a.round, a.inputs, a.recipes)
    fps = model_checks(a, b, out, jobs, paying=True)
    results = run.execute(jobs, out, cap, history_dirs=run_dirs(b) + (a.history or []), b=b,
                          lock_path=os.path.join(out, "media.lock.json"), model_fps=fps,
                          regenerate=a.regenerate_changed)
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
    if a.round == "full" and not a.inputs and not a.recipes:
        # numeric checks with no limit get one from this first full run, then it is frozen (limits.py)
        from . import catalog, limits
        new = limits.freeze(b, limits.propose(b, data["scored"], catalog.load(b)), a.round)
        if new:
            print(f"Limits set from this run for {len(new)} check(s), written to {limits.path(b)}:")
            for name, v in new.items():
                key = next(k for k in limits.KEY.values() if k in v)
                print(f"  {name}: {key} {v[key]}  ({v['from']})")
            limits.attach(b)
            data = score.recheck(b, data, out)  # the values just measured, against the limits just set
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
    if a.action == "plan":
        rows = score.plan(b, reg)
        print("| # | Check | Answers | Metric | Origin | Trust | Fails when |\n|---|---|---|---|---|---|---|")
        for i, r in enumerate(rows, 1):
            limit = ("never: " + r["limit"] if r["limit"].startswith("none") else r["limit"] if r["limit"].startswith("worse")
                     else "outside " + r["limit"] if r["limit"][0] != "y" else "not " + r["limit"])
            print(f"| {i} | {r['label']} | {'; '.join(r['needs']) or 'no requirement'} | `{r['id']}` | {r['origin']} | {r['trust']} | {limit} |")
        print()
        for i, r in enumerate(rows, 1):
            qs = "".join(f"\n     - {q}" for q in r["questions"])
            print(f"{i}. **{r['label']}**: {r['what']}{qs}")
        for w in score.coverage_errors(b):
            print(f"\nx {w}")
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
    seen = {}
    for d in run_dirs(b):
        for r in run.read_results(d):
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
            p.add_argument("--regenerate-changed", action="store_true",
                           help="make cached results again when their model's published details changed since")
        if name in ("estimate", "run"):
            p.add_argument("--skip-model-check", action="store_true",
                           help="do not check recipes against the models' schemas, nor record what the models publish")
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
    mp = sub.add_parser("metrics", help="list metrics (library + bench), show this bench's checks for the user to choose from (plan), run the controls, or print the registry")
    mp.add_argument("action", choices=["list", "plan", "control", "markdown"])
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
