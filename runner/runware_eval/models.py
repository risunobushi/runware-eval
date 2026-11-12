"""What Runware publishes about each model, used twice before anything is paid.

1. Parameter check. Runware runs and bills a request with a field it does not know (a typo runs at the
   model's default). `check_jobs` validates one request per recipe against the model's published JSON
   Schema and names every field or value the schema does not allow.

2. Model record. The same model id can change between two runs of a bench: status, price, a field
   added or removed, a default moved. `record` keeps a small snapshot per model in the run folder
   (`models.json`), `changes` compares the newest snapshot of earlier runs with today's, and every
   result row is stamped with the snapshot it was generated under (`model_fp`).

What this cannot see: a model whose weights change while its published schema, status and price stay
the same, and rules the API enforces that the schema does not state.
"""
import hashlib
import json
import os
import time

from . import api

FILE = "models.json"
SKIP = ("auto",)  # the router has no schema of its own
_DOCS = {}


def document(air):
    """The model's published OpenAPI document, or None (not listed, or the docs site is unreachable)."""
    if air not in _DOCS:
        try:
            _DOCS[air] = None if air in SKIP else api.model_schema(air)
        except Exception:  # noqa: BLE001  no network: the check is skipped and said so, the run is not blocked
            _DOCS[air] = None
    return _DOCS[air]


def _item(doc):
    body = ((doc or {}).get("components") or {}).get("schemas", {}).get("RequestBody") or {}
    return body.get("items") if isinstance(body.get("items"), dict) else None


# ---------------------------------------------------------------- parameter check

def _where(err):
    path = [str(p) for p in list(err.absolute_path)[1:]]  # [0] is the task's place in the posted array
    return ".".join(path)


def _say(err):
    at, v = _where(err), err.validator
    if v == "additionalProperties":
        import re
        names = re.findall(r"'([^']+)'", err.message.split(" were unexpected")[0].split(" was unexpected")[0])
        allowed = sorted((err.schema.get("properties") or {}).keys())
        return [f"`{(at + '.' if at else '') + n}` is not a field of this model"
                + (f" (did you mean `{close[0]}`?)" if (close := _close(n, allowed)) else "") for n in names]
    if v in ("enum", "const"):
        allowed = err.schema.get("enum") or [err.schema.get("const")]
        return [f"`{at}`: {err.instance!r} is not allowed (allowed: {', '.join(map(str, allowed[:12]))}"
                f"{', ...' if len(allowed) > 12 else ''})"]
    if v in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems", "maxItems",
             "minLength", "maxLength"):
        return [f"`{at}`: {err.instance if not isinstance(err.instance, (list, str)) else 'its length'} breaks "
                f"{v} {err.validator_value}"]
    if v == "required":
        return [f"{'`' + at + '`: ' if at else ''}{err.message}"]
    if v in ("anyOf", "oneOf") and err.context:
        # report the branch that came closest, not every branch
        best = min(err.context, key=lambda e: (-len(e.absolute_path), e.validator != "additionalProperties"))
        return _say(best) if len(best.absolute_path) > len(err.absolute_path) else \
            [f"`{at}`: {_short(err.instance)} fits none of the forms this model accepts"]
    return [f"`{at}`: {err.message[:160]}" if at else err.message[:160]]


def _short(x):
    s = json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x
    return s if len(s) <= 60 else s[:57] + "..."


def _close(name, allowed):
    import difflib
    return difflib.get_close_matches(name, allowed, n=1, cutoff=0.7)


HARD = ("additionalProperties", "enum", "const", "type", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
        "multipleOf", "minItems", "maxItems", "minLength", "maxLength")


def _level(err):
    """`stop`: a field the model does not have, or a value outside what it allows. `warn`: a field the
    schema calls required, and anything under a conditional rule (if/then): there the published schema
    has been seen to be stricter than the API, so these are shown and do not stop a run."""
    path = [str(x) for x in err.absolute_schema_path]
    leaf = err
    if err.validator in ("anyOf", "oneOf") and err.context:
        leaf = min(err.context, key=lambda e: (-len(e.absolute_path), e.validator != "additionalProperties"))
    return "stop" if leaf.validator in HARD and "then" not in path and "else" not in path else "warn"


def check_task(task, doc):
    """Problems with one request as (level, sentence). Empty: the schema allows it. None: no schema."""
    if not _item(doc):
        return None
    from jsonschema import Draft202012Validator
    schema = {"$ref": "#/components/schemas/RequestBody", "components": doc["components"]}
    out = []
    for err in Draft202012Validator(schema).iter_errors([task]):
        for line in _say(err):
            if not any(line == x[1] for x in out):
                out.append((_level(err), line))
    return out


def check_jobs(jobs, b=None):
    """One request per recipe (and its `then` step) against its model's schema.
    Returns ({recipe id: {"stop": [...], "warn": [...]}}, [recipe ids that could not be checked])."""
    problems, unchecked, seen = {}, [], set()
    for j in jobs:
        if j["recipe"] in seen:
            continue
        seen.add(j["recipe"])
        steps = [("", j["task"])]
        then = (j.get("_recipe") or {}).get("then")
        if then:
            from . import bench as benchmod
            fake = "https://im.runware.ai/image/00000000-0000-0000-0000-000000000000.png"
            ctx = {"bench": b or {}, "input": j["_inp"], "recipe": j["_recipe"], "seed": j["seed"], "prev": fake, "mask_url": fake}
            try:
                steps.append(("then-step: ", benchmod.then_task(then, ctx)))
            except Exception:  # noqa: BLE001  a placeholder only known at run time: the first step is still checked
                pass
        for prefix, task in steps:
            if task.get("model") in SKIP:
                continue
            found = check_task(task, document(task.get("model")))
            if found is None:
                unchecked.append(j["recipe"])
            for level, line in found or []:
                problems.setdefault(j["recipe"], {"stop": [], "warn": []})[level].append(prefix + line)
    return problems, sorted(set(unchecked))


# ---------------------------------------------------------------- model record

OWN = ("taskType", "taskUUID", "model", "webhookURL", "includeCost", "uploadEndpoint", "ttl", "deliveryMethod")


def _fields(node, path="", out=None, depth=0):
    """The request's fields, flat: path -> what the schema says about it (type, allowed values, range, default)."""
    out = {} if out is None else out
    for name, spec in sorted((node.get("properties") or {}).items()):
        if not isinstance(spec, dict) or (not path and name in OWN):
            continue
        here = f"{path}.{name}" if path else name
        out[here] = {k: spec[k] for k in ("type", "enum", "const", "minimum", "maximum", "multipleOf", "default") if k in spec}
        if depth < 4:
            _fields(spec, here, out, depth + 1)
            if isinstance(spec.get("items"), dict):
                _fields(spec["items"], here + "[]", out, depth + 1)
    return out


def _prices(info):
    p = info.get("x-pricing") or {}
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except ValueError:
            p = {}
    rows = {}
    for r in p.get("rates") or []:
        if isinstance(r.get("amount"), (int, float)):
            rows[str(r.get("unit") or r.get("name") or r.get("description") or f"rate {len(rows) + 1}")] = r["amount"]
    for r in p.get("measured") or []:
        if isinstance(r.get("price"), (int, float)) and r.get("configuration"):
            rows[r["configuration"]] = r["price"]
    return rows


def snapshot(air, doc=None):
    """What is published about a model today, small enough to keep with every run. None if not listed."""
    doc = document(air) if doc is None else doc
    item = _item(doc)
    if not item:
        return None
    info = doc.get("info") or {}
    snap = {"status": info.get("x-status"), "version": info.get("version"), "prices": _prices(info),
            "fields": _fields(item), "required": sorted(item.get("required") or []),
            # the conditional rules (allOf / if-then) are not listed field by field: a hash says they moved
            "rules": hashlib.sha1(json.dumps(item.get("allOf") or [], sort_keys=True).encode()).hexdigest()[:12]}
    snap["fp"] = hashlib.sha1(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:12]
    return snap


def diff(old, new):
    """What changed between two snapshots of one model, as short sentences (most consequential first)."""
    out = []
    if old.get("status") != new.get("status"):
        out.append(f"status {old.get('status')} → {new.get('status')}")
    if old.get("version") != new.get("version"):
        out.append(f"version {old.get('version')} → {new.get('version')}")
    po, pn = old.get("prices") or {}, new.get("prices") or {}
    moved = [f"{k}: ${po[k]:g} → ${pn[k]:g}" for k in po if k in pn and po[k] != pn[k]]
    if moved:
        out.append("price " + "; ".join(moved[:4]) + (f" (+{len(moved) - 4} more)" if len(moved) > 4 else ""))
    elif set(po) != set(pn):
        out.append("the price list has different entries")
    fo, fn = old.get("fields") or {}, new.get("fields") or {}
    gone, added = sorted(set(fo) - set(fn)), sorted(set(fn) - set(fo))
    top = lambda names: [n for n in names if not any(n != m and n.startswith(m + ".") or n.startswith(m + "[]") for m in names)]
    if gone:
        out.append("field removed: " + ", ".join(top(gone)[:8]))
    if added:
        out.append("field added: " + ", ".join(top(added)[:8]))
    for name in sorted(set(fo) & set(fn)):
        a, b = fo[name], fn[name]
        if a.get("default") != b.get("default"):
            out.append(f"default of {name}: {a.get('default')!r} → {b.get('default')!r}")
        for k, word in (("enum", "allowed values"), ("minimum", "minimum"), ("maximum", "maximum"), ("type", "type")):
            if a.get(k) != b.get(k):
                out.append(f"{word} of {name}: {_short(a.get(k))} → {_short(b.get(k))}")
    if old.get("required") != new.get("required"):
        out.append(f"required fields: {', '.join(old.get('required') or [])} → {', '.join(new.get('required') or [])}")
    if not out and old.get("rules") != new.get("rules"):
        out.append("the rules between fields changed (which fields need or exclude each other)")
    return out


def read(out_dir):
    path = os.path.join(out_dir, FILE)
    if not os.path.exists(path):
        return {}
    return json.load(open(path, encoding="utf8"))


def last_seen(dirs):
    """The newest snapshot of each model across run folders: {air: snapshot with `seen`}."""
    best = {}
    for d in dirs:
        for air, hist in read(d).items():
            if hist and (air not in best or hist[-1]["seen"] > best[air]["seen"]):
                best[air] = hist[-1]
    return best


def changes(airs, dirs):
    """Compare today's published state of each model with the newest snapshot in `dirs`.
    Returns (today {air: snapshot}, changed {air: {"since": date, "what": [sentences], "old": fp}})."""
    before, today, changed = last_seen(dirs), {}, {}
    for air in sorted(set(airs) - set(SKIP)):
        snap = snapshot(air)
        if not snap:
            continue
        today[air] = snap
        old = before.get(air)
        if old and old["fp"] != snap["fp"]:
            changed[air] = {"since": old["seen"], "old": old["fp"], "what": diff(old, snap) or ["published details changed"]}
    return today, changed


def record(out_dir, today, changed=None):
    """Append today's snapshot to the run folder's history when it is new there, with what changed."""
    hist = read(out_dir)
    now = time.strftime("%Y-%m-%d")
    for air, snap in today.items():
        rows = hist.setdefault(air, [])
        if rows and rows[-1]["fp"] == snap["fp"]:
            continue
        row = {**snap, "seen": now}
        if (changed or {}).get(air):
            row["changed"] = changed[air]["what"]
            row["previous"] = {"fp": changed[air]["old"], "seen": changed[air]["since"]}
        rows.append(row)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, FILE), "w", encoding="utf8") as f:
        json.dump(hist, f, indent=1, ensure_ascii=False)
    return hist


def stale(results, out_dir):
    """Results generated under an older snapshot than the newest one this folder knows for their model:
    {result hash: {"model", "since", "what"}}. Rows from before the record existed carry no stamp and
    are not judged either way."""
    hist, out = read(out_dir), {}
    for r in results:
        rows = hist.get(r.get("model")) or []
        if not rows or not r.get("model_fp") or r["model_fp"] == rows[-1]["fp"]:
            continue
        known = [x["fp"] for x in rows]
        after = rows[known.index(r["model_fp"]) + 1:] if r["model_fp"] in known else rows[-1:]
        what = [w for x in after for w in x.get("changed") or []]
        out[r["hash"]] = {"model": r["model"], "since": after[0]["seen"], "what": what or ["published details changed"]}
    return out
