"""Limits for numeric checks, set from the bench's first full run and then frozen.

There is no "nothing changed" baseline to measure against: a model changes pixels just by encoding and
decoding the picture, and nobody outside can measure that round trip for a closed model. What real models
return is the only baseline there is. So a numeric check that has no limit in bench.yaml gets one from
the first full run:

    limit = median of the recipes' medians, moved towards "worse" by a margin
    margin = the larger of: the typical spread between draws of one recipe,
                            the metric's smallest difference worth caring about (`tolerance` in its META)

Every recipe counts once, whatever its number of draws or inputs, and a median is not pulled by one
recipe that did nothing or broke. An output fails when it is worse than the typical recipe by more than
a re-roll explains. If every recipe is poor, the typical one still passes: that is the ceiling of what
the models can do on this brief, and the report says where each limit came from.

The limits are written to `limits.yaml` next to bench.yaml, once. Later runs read them and never move
them, so a recipe added later is held to the same line. A limit in bench.yaml always wins; `limit: none`
on a check keeps it measured only. To change a limit, edit `limits.yaml` or put the limit in bench.yaml;
to have them set again from the results in a run folder, delete the entry (or the file) and score again.
"""
import os
import time

import numpy as np
import yaml

FILE = "limits.yaml"
HEAD = ("# Limits set by runware-eval from this bench's first full run, then frozen (see `from`).\n"
        "# A limit written in bench.yaml wins over one here. Delete an entry to have it set again on the next\n"
        "# scoring of the full run; edit `max` / `min` / `abs_max` to change it by hand.\n")
RUBRIC_TOLERANCE = 0.5  # judge rubric scores (1 to 5): half a point
KEY = {"lower": "max", "higher": "min", "closer_to_zero": "abs_max"}  # the limit a direction gets


def path(b):
    return os.path.join(b["_dir"], FILE)


def read(b):
    p = path(b)
    if not os.path.exists(p):
        return {}
    return yaml.safe_load(open(p, encoding="utf8")) or {}


def _checks(b):
    from .score import all_checks, label
    for _, opt in all_checks(b):
        yield label(opt), opt


def _open(opt):
    """A check that may get a limit from the results: none in bench.yaml, and not opted out."""
    from .score import row_mode
    return opt.get("limit") != "none" and "limitFrom" not in opt and row_mode(opt) != "gate"


def attach(b):
    """Put the frozen limits on the bench's checks (bench.yaml's own limits win). Returns how many."""
    saved, n = read(b), 0
    for name, opt in _checks(b):
        entry = saved.get(name)
        if not entry or not _open(opt):
            continue
        key = next((k for k in KEY.values() if k in entry), None)
        if key:
            opt[key] = entry[key]
            opt["limitFrom"] = entry.get("from", "set from the first full run")
            n += 1
    return n


def direction(opt, reg):
    if opt.get("id") == "vlm_rubric":
        return "higher", RUBRIC_TOLERANCE
    meta = (reg.get(opt["id"]) or {}).get("meta") or {}
    return meta.get("direction") or "", float(meta.get("tolerance") or 0.0)


def _num(x):
    return f"{x:.3g}"


def propose(b, scored, reg):
    """A limit for every open numeric check, from scored outputs: {label: {max|min|abs_max, from, ...}}.
    Needs at least two recipes with a value; a check with fewer gets none."""
    out = {}
    for name, opt in _checks(b):
        if not _open(opt):
            continue
        way, tol = direction(opt, reg)
        if way not in KEY:
            continue
        per, groups = {}, {}
        for s in scored:
            for m in s.get("metrics", []):
                v = (m.get("values") or {}).get("value") if m.get("label") == name and m.get("status") == "ok" else None
                if isinstance(v, (int, float)) and np.isfinite(v):
                    v = abs(v) if way == "closer_to_zero" else float(v)
                    per.setdefault(s["recipe"], []).append(v)
                    groups.setdefault((s["recipe"], s["input"]), []).append(v)
        if len(per) < 2:
            continue
        centre = float(np.median([np.median(v) for v in per.values()]))
        ranges = [max(v) - min(v) for v in groups.values() if len(v) > 1]
        spread = float(np.median(ranges)) if ranges else 0.0
        margin = max(spread, tol)
        limit = centre - margin if way == "higher" else centre + margin
        limit = float(f"{limit:.4g}")
        why = (f"median of {len(per)} recipes ({_num(centre)}) {'minus' if way == 'higher' else 'plus'} {_num(margin)}: "
               + (f"the spread between draws ({_num(spread)})" if spread >= tol and ranges
                  else f"the metric's smallest difference that counts ({_num(tol)})" if tol
                  else "no margin (one draw per recipe, and the metric states no smallest difference)")
               + (f", larger than {'the smallest difference that counts' if spread >= tol else 'the spread between draws'} "
                  f"({_num(tol if spread >= tol else spread)})" if ranges and tol and spread != tol else ""))
        out[name] = {KEY[way]: limit, "from": why, "recipes": len(per), "outputs": sum(len(v) for v in per.values())}
    return out


def freeze(b, new, run_name):
    """Add new limits to limits.yaml. Entries that are already there are never changed."""
    saved = read(b)
    added = {k: {**v, "set": time.strftime("%Y-%m-%d"), "run": run_name} for k, v in new.items() if k not in saved}
    if added:
        saved.update(added)
        with open(path(b), "w", encoding="utf8") as f:
            f.write(HEAD + yaml.safe_dump(saved, sort_keys=False, allow_unicode=True, width=200))
    return added


def listed(b):
    """The frozen limits in use on this bench, for the report: [(label, 'at most 6.67', from)]."""
    word = {"max": "at most", "min": "at least", "abs_max": "within ±"}
    rows = []
    for name, opt in _checks(b):
        if opt.get("limitFrom"):
            key = next(k for k in KEY.values() if k in opt)
            rows.append((name, f"{word[key]} {_num(opt[key])}", opt["limitFrom"]))
    return rows
