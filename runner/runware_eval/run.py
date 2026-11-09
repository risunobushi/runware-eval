"""Execute bench jobs: cached, budget-guarded, concurrent. Writes images, masks and results.jsonl."""
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from . import api
from . import bench as benchmod
from .score import input_region

MASK_MODEL = "runware:112@5"  # BiRefNet General


def read_results(out_dir):
    path = os.path.join(out_dir, "results.jsonl")
    if not os.path.exists(path):
        return []
    return [json.loads(line) for line in open(path, encoding="utf8") if line.strip()]


def append_result(out_dir, row):
    with open(os.path.join(out_dir, "results.jsonl"), "a", encoding="utf8") as f:
        f.write(json.dumps(row) + "\n")


def estimate(jobs, results):
    """Per-job cost: measured average for that recipe if any run exists, else the listed price."""
    measured = {}
    for r in results:
        if r.get("status") == "success" and r.get("cost") is not None:
            measured.setdefault(r["recipe"], []).append(r["cost"])
    rows, listed = [], {}
    for j in jobs:
        if j["recipe"] in measured:
            cost, source = float(np.mean(measured[j["recipe"]])), "measured"
        else:
            if j["model"] not in listed:
                listed[j["model"]] = api.listed_price(j["model"])
            cost, source = listed[j["model"]], "listed (max)"
        rows.append({**j, "est_cost": cost, "est_source": source})
    return rows


def mask_from(url, path):
    """Product mask (white = product) via background removal on Runware."""
    res = api.run_task({"taskType": "removeBackground", "taskUUID": str(uuid.uuid4()), "model": MASK_MODEL,
                        "inputs": {"image": url}, "outputFormat": "PNG", "includeCost": True})
    if res["status"] != "success":
        raise RuntimeError(f"Mask failed: {res.get('error')}")
    api.download(res["imageURL"], path + ".rgba.png")
    alpha = Image.open(path + ".rgba.png").split()[-1]
    Image.fromarray(((np.asarray(alpha) > 127) * 255).astype(np.uint8)).save(path)
    os.remove(path + ".rgba.png")
    return res.get("cost") or 0.0


def execute(jobs, out_dir, max_usd, workers=6, log=print):
    os.makedirs(os.path.join(out_dir, "masks"), exist_ok=True)
    results = read_results(out_dir)
    done = {r["hash"] for r in results if r.get("status") == "success"
            and os.path.exists(os.path.join(out_dir, r["file"]))}
    todo = [j for j in jobs if j["hash"] not in done]
    spent = sum(r.get("cost") or 0 for r in results) + sum(r.get("eval_cost") or 0 for r in results)
    est = estimate(todo, results)
    unknown = [e["recipe"] for e in est if e["est_cost"] is None]
    projected = sum(e["est_cost"] or 0 for e in est)
    log(f"{len(jobs) - len(todo)} cached, {len(todo)} to run. Spent so far ${spent:.3f}, "
        f"projected ${projected:.3f}, cap ${max_usd:.2f}.")
    if unknown:
        log(f"No price known for: {', '.join(sorted(set(unknown)))}. They count as $0 in the projection.")
    if spent + projected > max_usd:
        raise SystemExit(f"Stopped: ${spent + projected:.3f} would exceed the ${max_usd:.2f} cap. "
                         "Raise budget.max_usd in bench.yaml or run fewer recipes.")

    def one(j):
        res = api.run_task(j["task"])
        row = {k: j[k] for k in ("input", "recipe", "seed", "model", "hash")}
        row.update(taskUUID=j["task"]["taskUUID"], status=res["status"], cost=res.get("cost"),
                   latency_s=res.get("latency_s"), error=res.get("error"))
        if res["status"] == "success":
            url = res.get("imageURL") or res.get("videoURL")
            ext = os.path.splitext(url.split("?")[0])[1] or ".png"
            row["file"] = f"{j['input']}__{j['recipe']}__s{j['seed']}{ext}"
            row["url"] = url
            api.download(url, os.path.join(out_dir, row["file"]))
            try:
                row["eval_cost"] = mask_from(url, os.path.join(out_dir, "masks", row["file"].rsplit(".", 1)[0] + "_cut.png"))
            except RuntimeError as e:
                row["mask_error"] = str(e)
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(one, todo):
            append_result(out_dir, row)
            status = (f"${row['cost']:.4f} · {row['latency_s']}s" if row["status"] == "success"
                      else f"ERROR {row['error']}")
            log(f"  {row['input']} · {row['recipe']} · s{row['seed']}: {status}")
    return read_results(out_dir)


def ensure_input_masks(b, out_dir):
    """Resolve `regions.<name>: auto:<AIR>` into mask files once."""
    for inp in b["inputs"]:
        for name, spec in (inp.get("regions") or {}).items():
            if isinstance(spec, str) and spec.startswith("auto:"):
                target = os.path.join(out_dir, "masks", f"{os.path.splitext(os.path.basename(inp['path']))[0]}_{name}.png")
                if not os.path.exists(target):
                    mask_from(inp["_url"], target)
                inp["regions"][name] = os.path.abspath(target)  # absolute: out_dir may be on another drive


def ensure_recipe_masks(b, out_dir, lock_path):
    """Build and upload the model-input mask for every recipe with a `mask:` block, per input.

    `mask: { edit: <region>, polarity: white_is_edit | white_is_keep }`. Drawn at the input's exact
    size, because models such as Ideogram Precise Edit require matching dimensions.
    """
    os.makedirs(os.path.join(out_dir, "masks"), exist_ok=True)
    for r in b["recipes"]:
        spec = r.get("mask")
        if not spec:
            continue
        for inp in b["inputs"]:
            name = os.path.splitext(os.path.basename(inp["path"]))[0]
            edit = input_region(b, inp, spec["edit"])
            white = edit if spec.get("polarity", "white_is_edit") == "white_is_edit" else ~edit
            if white.all() or not white.any():
                raise ValueError(f"Mask for {r['id']} on {name} is all one colour; check `mask.edit`")
            path = os.path.join(out_dir, "masks", f"{name}__{r['id']}__input_mask.png")
            Image.fromarray((white * 255).astype(np.uint8)).save(path)
            rec = benchmod.upload(path, os.path.abspath(path), lock_path)
            inp.setdefault("_masks", {})[r["id"]] = rec["url"]
