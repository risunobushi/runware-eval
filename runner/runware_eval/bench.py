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


def load(path, resolve_recipes=True):
    b = _fix_bool_keys(yaml.safe_load(open(path, encoding="utf8")))
    b["_dir"] = os.path.dirname(os.path.abspath(path))
    b["_url_sha"] = {}
    if resolve_recipes:
        from .recipes import resolve_bench
        resolve_bench(b)
    return b


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


def fit(w, h, multiple=1, max_side=None, max_mp=None):
    s = 1.0
    if max_side:
        s = min(s, max_side / max(w, h))
    if max_mp:
        s = min(s, math.sqrt(max_mp * 1e6 / (w * h)))
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
    if token == "mask":
        url = ctx["input"].get("_masks", {}).get(ctx["recipe"]["id"])
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
        size = dict(ctx["recipe"].get("size", {}))
        if m.group(2):
            size["multiple"] = int(m.group(2))
        if m.group(3):
            size["max_side"] = int(m.group(3))
        w, h = fit(*ctx["input"]["_size"], **size)
        return w if m.group(1) == "width" else h
    media = media_entries(ctx["bench"])
    if token in media:
        return media[token]["_url"]
    raise ValueError(f"Unknown placeholder {value}")


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
                out.append({"input": stem(inp["path"]), "recipe": r["id"], "seed": seed,
                            "model": r["model"], "fp": r.get("_fp"), "hash": content_key(b, task),
                            "task": {**task, "taskUUID": str(uuid.uuid4())}})
    return out
