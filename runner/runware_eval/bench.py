"""Load a bench.yaml, upload its media once, and resolve recipe placeholders into API tasks.

Placeholders in recipe params:
  $input                     the input's media URL
  $input.width / .height     input size, adjusted by the recipe's `size` block
  $input.width_16[_max2048]  legacy form: multiple of 16, optional longest-side cap
  $seed                      the current seed
  $prompts.<name>            a prompt from the top-level `prompts` block
  $<name>                    URL of a top-level media entry, e.g. `lighting_ref: {path: ...}`
"""
import hashlib
import json
import math
import os
import re
import subprocess
import uuid

import yaml
from PIL import Image


def _fix_bool_keys(o):
    """YAML 1.1 reads keys like `on:` / `off:` / `yes:` as booleans. Turn them back into strings."""
    if isinstance(o, dict):
        return {({True: "on", False: "off"}.get(k, k) if isinstance(k, bool) else k): _fix_bool_keys(v)
                for k, v in o.items()}
    if isinstance(o, list):
        return [_fix_bool_keys(v) for v in o]
    return o


# Older spelling -> current name. Settings follow the camelCase of Runware's API (`maxPrice`, `taskType`).
# Old files keep working: they are renamed in memory when loaded, never rewritten on disk.
RENAMED = {"max_models": "maxModels", "pass_rule": "passRule", "recipe_dirs": "recipeDirs",
           "metric_dirs": "metricDirs", "judge_when": "judgeWhen"}
RENAMED_IN = {"judgeWhen": {"max_failed_checks": "maxFailedChecks"}, "calibration": {"label_count": "labelCount"},
              "budget": {"max_usd": "maxPrice"}}
RECIPE_SIZE = {"max_side": "maxSide", "max_mp": "maxMp"}
RECIPE_POST = {"transfer_detail": "transferDetail", "sigma_px": "sigmaPx", "feather_px": "featherPx"}


def rename_keys(d, names):
    """A copy of dict `d` with the keys in `names` renamed; a key already under its new name wins."""
    if not isinstance(d, dict):
        return d
    out = {k: v for k, v in d.items() if k not in names}
    for old, new in names.items():
        if old in d:
            out.setdefault(new, d[old])
    return out


def modern_recipe(r):
    """A recipe with the current spelling of its `size` and `post` keys."""
    r = dict(r)
    if isinstance(r.get("size"), dict):
        r["size"] = rename_keys(r["size"], RECIPE_SIZE)
    if isinstance(r.get("post"), list):
        r["post"] = [rename_keys(s, RECIPE_POST) for s in r["post"]]
    return r


def load(path, resolve_recipes=True):
    b = rename_keys(_fix_bool_keys(yaml.safe_load(open(path, encoding="utf8"))), RENAMED)
    for block, names in RENAMED_IN.items():
        if isinstance(b.get(block), dict):
            b[block] = rename_keys(b[block], names)
    b["_dir"] = os.path.dirname(os.path.abspath(path))
    b["_url_sha"] = {}
    if resolve_recipes:
        from .recipes import resolve_bench
        resolve_bench(b)
    return b


def max_price(b):
    """The most one full run may spend, in USD: `budget.maxPrice` (the Model Router's name for a price
    ceiling). `budget.max_usd`, the older spelling, still works."""
    budget = b.get("budget") or {}
    return budget.get("maxPrice", budget.get("max_usd"))  # the older name too: not every bench comes through load()


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def media_entries(b):
    """Every file the bench sends to Runware: inputs plus top-level `{path: ...}` references."""
    out = {stem(i["path"]): i for i in b["inputs"]}
    for k, v in b.items():
        if isinstance(v, dict) and "path" in v and k not in ("inputs",):
            out[k] = v
    return out


def upload(full, key, lock_path):
    """Upload a file once with the Runware CLI; the lock file maps it (by content hash) to its URL.

    URLs, not UUIDs, are sent to models: some provider-backed models fail to fetch a media UUID.
    """
    lock = json.load(open(lock_path, encoding="utf8")) if os.path.exists(lock_path) else {}
    digest = hashlib.sha1(open(full, "rb").read()).hexdigest()
    rec = lock.get(key)
    if not rec or rec.get("sha1") != digest:
        res = subprocess.run(["runware", "media", "upload", full, "-F", "json"], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Upload failed for {key}: {res.stderr.strip() or res.stdout.strip()}\n"
                               "Is the Runware CLI installed and signed in? (`runware auth status`)")
        up = json.loads(res.stdout)
        w, h = Image.open(full).size
        rec = {"uuid": up["mediaUUID"], "url": up["mediaURL"], "sha1": digest, "width": w, "height": h}
        lock[key] = rec
        json.dump(lock, open(lock_path, "w", encoding="utf8"), indent=2)
    return rec


def ensure_media(b, lock_path):
    """Upload every input and media reference once, and attach `_url` and `_size` to each entry."""
    for entry in media_entries(b).values():
        rec = upload(os.path.join(b["_dir"], entry["path"]), entry["path"], lock_path)
        entry["_url"], entry["_size"] = rec["url"], (rec["width"], rec["height"])
        b["_url_sha"][rec["url"]] = rec["sha1"]


def fit(w, h, multiple=1, maxSide=None, maxMp=None):
    s = 1.0
    if maxSide:
        s = min(s, maxSide / max(w, h))
    if maxMp:
        s = min(s, math.sqrt(maxMp * 1e6 / (w * h)))
    return (int(w * s) // multiple) * multiple, (int(h * s) // multiple) * multiple


def resolve(value, ctx):
    if isinstance(value, dict):
        return {k: resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, ctx) for v in value]
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    token = value[1:]
    if token == "input":
        return ctx["input"]["_url"]
    if token == "seed":
        return ctx["seed"]
    if token == "prev":
        return ctx["prev"]
    if token == "mask":
        url = ctx.get("mask_url") or ctx["input"].get("_masks", {}).get(ctx["recipe"]["id"])
        if not url:
            raise ValueError(f"Recipe {ctx['recipe']['id']} uses $mask but has no `mask:` block")
        return url
    if token == "judges":
        return ctx["bench"].get("judges")
    if token.startswith("prompts."):
        return " ".join(ctx["bench"]["prompts"][token.split(".", 1)[1]].split())
    if token.startswith("input."):
        attr = token.split(".", 1)[1]
        m = re.fullmatch(r"(width|height)(?:_(\d+))?(?:_max(\d+))?", attr)
        if not m:
            raise ValueError(f"Unknown placeholder {value}")
        size = rename_keys(dict(ctx["recipe"].get("size", {})), RECIPE_SIZE)
        if m.group(2):
            size["multiple"] = int(m.group(2))
        if m.group(3):
            size["maxSide"] = int(m.group(3))
        w, h = fit(*ctx["input"]["_size"], **size)
        return w if m.group(1) == "width" else h
    media = media_entries(ctx["bench"])
    if token in media:
        return media[token]["_url"]
    raise ValueError(f"Unknown placeholder {value}")


ROUTER = "auto"  # `model: auto`: Runware's Model Router picks the model for each request


def routing(b, r, ctx):
    """The `routing` block of a `model: auto` recipe, as sent. `allowedModels: bench` stands for every
    model the bench's other recipes call by name, so the router chooses among the models under test."""
    spec = resolve(dict(r.get("routing") or {}), ctx)
    if spec.get("allowedModels") == "bench":
        pool = sorted({x["model"] for x in ctx["bench"]["recipes"] if x["model"] != ROUTER})
        if len(pool) < 2:
            raise ValueError(f"Recipe '{r['id']}' has `allowedModels: bench`, which needs at least two other "
                             "models in the bench (the router's minimum for an allow-list).")
        spec["allowedModels"] = pool
    return spec


def content_key(b, task):
    """Identity of a task by content: the request with every uploaded file replaced by its hash.

    Independent of URLs, paths, recipe names and machines, so matching history can be reused.
    """
    def swap(v):
        if isinstance(v, dict):
            return {k: swap(x) for k, x in v.items()}
        if isinstance(v, list):
            return [swap(x) for x in v]
        return f"sha1:{b['_url_sha'][v]}" if isinstance(v, str) and v in b["_url_sha"] else v
    return hashlib.sha1(json.dumps(swap(task), sort_keys=True).encode()).hexdigest()[:20]


def jobs(b, round_name, only_inputs=None, only_recipes=None):
    """One job per (input, recipe, seed). Smoke round: first input (unless chosen), first seed."""
    inputs = [i for i in b["inputs"] if not only_inputs or stem(i["path"]) in only_inputs]
    recipes = [r for r in b["recipes"] if not only_recipes or r["id"] in only_recipes]
    cap = b.get("maxModels", b.get("max_models"))
    models = sorted({r["model"] for r in recipes} - {ROUTER})
    if cap and len(models) > cap:
        raise ValueError(f"{len(models)} models selected but maxModels is {cap}: choose which {cap} to test "
                         "(list their recipes under `recipes:` in bench.yaml, or pass --recipes).")
    seeds = b.get("seeds", [1])
    if round_name == "smoke":
        seeds = seeds[:1]
        if not only_inputs:
            inputs = inputs[:1]
    out = []
    for inp in inputs:
        for r in recipes:
            for seed in seeds:
                ctx = {"bench": b, "input": inp, "recipe": r, "seed": seed}
                params = resolve(r.get("params", {}), ctx)
                task = {"taskType": r.get("taskType", "imageInference"), "model": r["model"], **params,
                        "includeCost": True}
                base = content_key(b, task)
                if r["model"] == ROUTER:
                    if r.get("then") or r.get("post"):
                        raise ValueError(f"Recipe '{r['id']}': `model: auto` cannot have `then` or `post` steps yet.")
                    rt = routing(b, r, ctx)
                    if rt:
                        task["routing"] = rt
                    # the router may pick a different model on every call: each seed is its own draw,
                    # never a cache hit on another seed's result
                    base = hashlib.sha1(json.dumps([content_key(b, task), "draw", seed]).encode()).hexdigest()[:20]
                pipeline = bool(r.get("then") or r.get("post"))
                key = base if not pipeline else hashlib.sha1(json.dumps(
                    [base, r.get("_fp"), inp.get("regions")], sort_keys=True, default=str).encode()).hexdigest()[:20]
                out.append({"input": stem(inp["path"]), "recipe": r["id"], "seed": seed,
                            "model": r["model"], "fp": r.get("_fp"), "hash": key,
                            "base_hash": base if pipeline else None, "_inp": inp, "_recipe": r,
                            "task": {**task, "taskUUID": str(uuid.uuid4())}})
    return out
