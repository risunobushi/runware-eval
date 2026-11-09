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


def cmd_estimate(a):
    b, out = setup(a)
    bench.ensure_media(b, os.path.join(out, "media.lock.json"))
    jobs = bench.jobs(b, a.round, a.inputs, a.recipes)
    rows = run.estimate(jobs, run.read_results(out))
    total = sum(r["est_cost"] or 0 for r in rows)
    by = {}
    for r in rows:
        x = by.setdefault(r["recipe"], {"n": 0, "cost": r["est_cost"], "src": r["est_source"]})
        x["n"] += 1
    print(f"{'recipe':34} {'tasks':>5} {'$/task':>9}  source")
    for rid, x in by.items():
        c = f"{x['cost']:.4f}" if x["cost"] is not None else "?"
        print(f"{rid:34} {x['n']:>5} {c:>9}  {x['src']}")
    cap = (b.get("budget") or {}).get("max_usd")
    print(f"\n{len(rows)} tasks, about ${total:.3f}" + (f" (cap ${cap:.2f})" if cap else "")
          + ". Masks for scoring add a small amount per output.")
    print("Measured costs come from earlier runs in this folder; listed costs are the highest price in the "
          "model's schema. Runware has no reliable dry-run, so a smoke round is the way to measure.")


def cmd_run(a):
    b, out = setup(a)
    cap = (b.get("budget") or {}).get("max_usd")
    if cap is None:
        sys.exit("bench.yaml has no budget.max_usd: set a cap before running.")
    bench.ensure_media(b, os.path.join(out, "media.lock.json"))
    run.ensure_input_masks(b, out)
    jobs = bench.jobs(b, a.round, a.inputs, a.recipes)
    results = run.execute(jobs, out, cap)
    print(f"Done. Results in {out}")
    if not a.no_score:
        cmd_score(a, b, out, results)


def cmd_score(a, b=None, out=None, results=None):
    if b is None:
        b, out = setup(a)
        bench.ensure_media(b, os.path.join(out, "media.lock.json"))
        run.ensure_input_masks(b, out)
    data = score.score_all(b, out, results if results is not None else run.read_results(out))
    print(f"Scored {len(data['scored'])} outputs → {os.path.join(out, 'scores.json')}")
    cmd_report(a, b, out)


def cmd_report(a, b=None, out=None):
    if b is None:
        b, out = setup(a)
        bench.ensure_media(b, os.path.join(out, "media.lock.json"))
        run.ensure_input_masks(b, out)
    notes = json.load(open(a.notes, encoding="utf8")) if getattr(a, "notes", None) else None
    listed = {r["model"]: api.listed_price(r["model"]) for r in b["recipes"]}
    print("Report →", report.build(b, out, notes, listed))


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
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    try:
        a.fn(a)
    except api.RunwareError as err:
        sys.exit(str(err))


if __name__ == "__main__":
    main()
