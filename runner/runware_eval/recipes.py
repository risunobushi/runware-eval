"""Recipes as files: one YAML per recipe, fingerprinted, shareable between benches and people.

A recipe file is self-contained (model, params with prompts written out, size, mask, notes). The
only things it expects from a bench are named slots such as `$input` or `$lighting_ref`.

The fingerprint is a hash of what changes the request (taskType, model, params, size, mask), not of
the id or notes: renaming or re-annotating a recipe keeps its fingerprint, editing it changes it.
"""
import glob
import hashlib
import json
import os
import re

import yaml

FP_KEYS = ("taskType", "model", "params", "size", "mask", "then", "post")
FP_LINE = re.compile(r"^fingerprint:.*$", re.M)


def fingerprint(r):
    core = {k: r[k] for k in FP_KEYS if k in r}
    core.setdefault("taskType", "imageInference")
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def slots(r):
    """Placeholders a recipe needs from its bench."""
    found = set(re.findall(r'"\$([A-Za-z_][\w.]*)"', json.dumps([r.get("params", {}),
                                                                     (r.get("then") or {}).get("params", {})])))
    return sorted(found)


def dirs(b):
    return [os.path.join(b["_dir"], d) for d in (b.get("recipe_dirs") or ["recipes"])]


def load_file(path):
    r = yaml.safe_load(open(path, encoding="utf8"))
    r["_file"] = path
    fp = fingerprint(r)
    if r.get("fingerprint") != fp:
        # first fingerprint, or the recipe was edited: record the new one in the file
        text = open(path, encoding="utf8").read()
        line = f"fingerprint: {fp}   # written by runware-eval; changes when the request changes"
        text = FP_LINE.sub(line, text) if FP_LINE.search(text) else text.rstrip() + "\n" + line + "\n"
        open(path, "w", encoding="utf8").write(text)
        r["_edited_from"] = r.get("fingerprint")
    r["_fp"] = fp
    return r


def catalogue(b):
    """Every recipe file the bench can see, by id. Earlier folders win on duplicate ids."""
    out = {}
    for d in dirs(b):
        for path in sorted(glob.glob(os.path.join(d, "*.yaml")) + glob.glob(os.path.join(d, "*.yml"))):
            r = load_file(path)
            out.setdefault(r["id"], r)
    return out


def resolve_bench(b):
    """Turn `recipes:` (ids, `all`, or inline dicts) into recipe dicts with `_fp`."""
    spec = b.get("recipes", "all")
    cat = None
    if spec == "all" or any(isinstance(x, str) for x in (spec if isinstance(spec, list) else [])):
        cat = catalogue(b)
    if spec == "all":
        chosen = list(cat.values())
    else:
        chosen = []
        for x in spec:
            if isinstance(x, str):
                if x not in cat:
                    raise ValueError(f"Recipe '{x}' not found in {', '.join(dirs(b))}")
                chosen.append(cat[x])
            else:
                chosen.append({**x, "_fp": fingerprint(x)})
    media = {k for k, v in b.items() if isinstance(v, dict) and "path" in v}
    builtin = {"input", "seed", "mask", "judges", "prev"}
    for r in chosen:
        missing = [s for s in slots(r) if s.split(".")[0] not in builtin | media
                   and not (s.startswith("prompts.") and s.split(".", 1)[1] in (b.get("prompts") or {}))]
        if missing:
            raise ValueError(f"Recipe '{r['id']}' needs {', '.join('$' + m for m in missing)}: add "
                             f"{'them' if len(missing) > 1 else 'it'} to bench.yaml (e.g. "
                             f"`{missing[0]}: {{ path: ... }}` for a reference image).")
    b["recipes"] = chosen
    return chosen


def _inline_prompts(params, prompts):
    if isinstance(params, dict):
        return {k: _inline_prompts(v, prompts) for k, v in params.items()}
    if isinstance(params, list):
        return [_inline_prompts(v, prompts) for v in params]
    if isinstance(params, str) and params.startswith("$prompts."):
        return " ".join(prompts[params.split(".", 1)[1]].split())
    return params


class _Literal(str):
    pass


def _dump(r):
    def lit(d, rep):
        return d.represent_scalar("tag:yaml.org,2002:str", rep, style=">")

    yaml.SafeDumper.add_representer(_Literal, lit)
    body = {k: v for k, v in r.items() if not k.startswith("_") and k != "fingerprint"}
    if isinstance(body.get("notes"), str):
        body["notes"] = _Literal(" ".join(body["notes"].split()))
    p = body.get("params", {})
    if isinstance(p.get("positivePrompt"), str):
        p["positivePrompt"] = _Literal(p["positivePrompt"])
    text = "# runware-eval recipe. Copy this file into another bench's recipes/ folder to reuse it.\n"
    text += yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)
    return text + f"fingerprint: {fingerprint(r)}   # written by runware-eval; changes when the request changes\n"


def extract(b, bench_path):
    """Move inline recipes into recipes/<id>.yaml, write prompts out, and point bench.yaml at them."""
    inline = [r for r in yaml.safe_load(open(bench_path, encoding="utf8")).get("recipes", []) if isinstance(r, dict)]
    if not inline:
        return []
    target = dirs(b)[0]
    os.makedirs(target, exist_ok=True)
    written = []
    for r in inline:
        r = {**r, "params": _inline_prompts(r.get("params", {}), b.get("prompts") or {})}
        path = os.path.join(target, f"{r['id']}.yaml")
        if os.path.exists(path):
            raise FileExistsError(f"{path} already exists; not overwriting")
        open(path, "w", encoding="utf8").write(_dump(r))
        written.append(path)
    text = open(bench_path, encoding="utf8").read()
    start = re.search(r"^recipes:\s*$", text, re.M)
    end = re.search(r"^\S", text[start.end():], re.M)
    tail = text[start.end() + end.start():] if end else ""
    ids = "\n".join(f"  - {r['id']}" for r in inline)
    block = (f"recipes:   # files in {os.path.relpath(target, os.path.dirname(bench_path))}/; "
             f"use `all` for every file there\n{ids}\n\n")
    open(bench_path + ".pre-extract.bak", "w", encoding="utf8").write(text)
    open(bench_path, "w", encoding="utf8").write(text[:start.start()] + block + tail)
    return written
