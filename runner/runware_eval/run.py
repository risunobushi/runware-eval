"""Execute bench jobs: cached, budget-guarded, concurrent. Writes images, masks and results.jsonl."""
import json
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor

import cv2
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


def history(dirs):
    """Successful results by content key across run folders, with the folder they live in."""
    found = {}
    for d in dirs:
        for r in read_results(d):
            if r.get("status") == "success" and r.get("file") and os.path.exists(os.path.join(d, r["file"])):
                found.setdefault(r["hash"], (d, r))
    return found


def reuse(j, src_dir, src, out_dir):
    """Copy a matching past output (and its mask) into this run under this run's names."""
    ext = os.path.splitext(src["file"])[1]
    name = f"{j['input']}__{j['recipe']}__s{j['seed']}{ext}"
    shutil.copyfile(os.path.join(src_dir, src["file"]), os.path.join(out_dir, name))
    m_src = os.path.join(src_dir, "masks", src["file"].rsplit(".", 1)[0] + "_cut.png")
    if os.path.exists(m_src):
        shutil.copyfile(m_src, os.path.join(out_dir, "masks", name.rsplit(".", 1)[0] + "_cut.png"))
    row = {**src, **{k: j[k] for k in ("input", "recipe", "seed", "model", "fp", "hash")},
           "file": name, "reused_from": os.path.abspath(src_dir), "eval_cost": 0.0}
    return row


def restore(cur_path, inp_path, region, feather_px, out_path):
    """Paste the original pixels of `region` back over the output, with a soft edge (no API call)."""
    orig = Image.open(inp_path).convert("RGB")
    W, H = orig.size
    cur = Image.open(cur_path).convert("RGB").resize((W, H), Image.BICUBIC)
    a = region.astype(np.float32)
    if feather_px:
        k = int(feather_px) * 2 + 1
        a = cv2.GaussianBlur(a, (k, k), feather_px / 2)
    a = a[..., None]
    comp = a * np.asarray(orig, np.float32) + (1 - a) * np.asarray(cur, np.float32)
    Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8)).save(out_path)
    return out_path


def transfer_detail(cur_path, inp_path, region, sigma_px, feather_px, out_path):
    """Frequency separation: inside `region`, keep the output's lighting (low frequencies) and put back
    the original's fine detail (high frequencies: lettering, stitching). Local, no API call."""
    orig = np.asarray(Image.open(inp_path).convert("RGB"), np.float32)
    H, W = orig.shape[:2]
    cur = np.asarray(Image.open(cur_path).convert("RGB").resize((W, H), Image.BICUBIC), np.float32)
    blur = lambda x: cv2.GaussianBlur(x, (0, 0), sigma_px)
    detail = blur(cur) + (orig - blur(orig))
    a = region.astype(np.float32)
    if feather_px:
        a = cv2.GaussianBlur(a, (0, 0), feather_px / 2)
    a = a[..., None]
    comp = a * detail + (1 - a) * cur
    Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8)).save(out_path)
    return out_path


def run_pipeline(j, b, out_dir, bases, lock_path):
    """Base generation (reused when an identical plain recipe already produced it), then the recipe's
    `then` step (a second task on the first output) and `post` steps (local edits)."""
    r, inp = j["_recipe"], j["_inp"]
    row = {k: j[k] for k in ("input", "recipe", "seed", "model", "fp", "hash", "base_hash")}
    row.update(status="success", cost=0.0, spend=0.0, latency_s=0.0, steps=[])
    os.makedirs(os.path.join(out_dir, "steps"), exist_ok=True)
    stem_ = f"{j['input']}__{j['recipe']}__s{j['seed']}"
    if j["base_hash"] in bases:
        d, f, url, cost = bases[j["base_hash"]]
        cur_path, cur_url = os.path.join(d, f), url
        row["cost"] += cost or 0
        row["steps"].append(f"base reused from {f}")
    else:
        res = api.run_task(j["task"])
        if res["status"] != "success":
            return {**row, "status": "error", "error": res.get("error")}
        cur_url = res["imageURL"]
        cur_path = os.path.join(out_dir, "steps", stem_ + "__base" + os.path.splitext(cur_url)[1])
        api.download(cur_url, cur_path)
        row["cost"] += res.get("cost") or 0
        row["spend"] += res.get("cost") or 0
        row["latency_s"] += res.get("latency_s") or 0
        row["steps"].append("base generated")
    if not cur_url:
        cur_url = benchmod.upload(cur_path, os.path.abspath(cur_path), lock_path)["url"]
    then = r.get("then")
    if then:
        ctx = {"bench": b, "input": inp, "recipe": r, "seed": j["seed"], "prev": cur_url}
        if r.get("mask"):
            w, h = Image.open(cur_path).size  # the mask must match the image it is applied to
            edit_ = input_region(b, inp, r["mask"]["edit"])
            white = edit_ if r["mask"].get("polarity", "white_is_edit") == "white_is_edit" else ~edit_
            mpath = os.path.join(out_dir, "masks", stem_ + "__step2_mask.png")
            Image.fromarray((white * 255).astype(np.uint8)).resize((w, h), Image.NEAREST).save(mpath)
            ctx["mask_url"] = benchmod.upload(mpath, os.path.abspath(mpath), lock_path)["url"]
        params = benchmod.resolve(then.get("params", {}), ctx)
        task = {"taskType": then.get("taskType", "imageInference"), "taskUUID": str(uuid.uuid4()),
                "model": then["model"], **params, "includeCost": True}
        res = api.run_task(task)
        if res["status"] != "success":
            return {**row, "status": "error", "error": f"then-step: {res.get('error')}"}
        cur_url = res["imageURL"]
        cur_path = os.path.join(out_dir, "steps", stem_ + "__then" + os.path.splitext(cur_url)[1])
        api.download(cur_url, cur_path)
        row["cost"] += res.get("cost") or 0
        row["spend"] += res.get("cost") or 0
        row["latency_s"] += res.get("latency_s") or 0
        row["steps"].append(f"then {then['model']}")
    pre_post_url = cur_url
    for step in r.get("post") or []:
        if "transfer_detail" in step:
            region = input_region(b, inp, step["transfer_detail"])
            cur_path = transfer_detail(cur_path, os.path.join(b["_dir"], inp["path"]), region,
                                       step.get("sigma_px", 6), step.get("feather_px", 6),
                                       os.path.join(out_dir, "steps", stem_ + "__post.png"))
            cur_url = None
            row["steps"].append(f"transfer detail {step['transfer_detail']}")
        if "restore" in step:
            region = input_region(b, inp, step["restore"])
            cur_path = restore(cur_path, os.path.join(b["_dir"], inp["path"]), region, step.get("feather_px", 4),
                               os.path.join(out_dir, "steps", stem_ + "__post.png"))
            cur_url = None
            row["steps"].append(f"restore {step['restore']}")
    row["file"] = stem_ + os.path.splitext(cur_path)[1]
    shutil.copyfile(cur_path, os.path.join(out_dir, row["file"]))
    row["url"] = cur_url
    try:  # product outline: post steps only touch small regions, so the pre-post image is used
        row["eval_cost"] = mask_from(pre_post_url, os.path.join(out_dir, "masks", stem_ + "_cut.png"))
    except RuntimeError as e:
        row["mask_error"] = str(e)
    row["latency_s"] = round(row["latency_s"], 1)
    return row


def execute(jobs, out_dir, max_usd, workers=6, log=print, history_dirs=(), b=None, lock_path=None):
    os.makedirs(os.path.join(out_dir, "masks"), exist_ok=True)
    results = read_results(out_dir)
    done = {r["hash"] for r in results if r.get("status") == "success"
            and os.path.exists(os.path.join(out_dir, r["file"]))}
    past = history([d for d in history_dirs if os.path.abspath(d) != os.path.abspath(out_dir)])
    reused = 0
    for j in jobs:
        if j["hash"] not in done and j["hash"] in past:
            append_result(out_dir, reuse(j, *past[j["hash"]], out_dir))
            done.add(j["hash"])
            reused += 1
    if reused:
        log(f"Reused {reused} matching result(s) from earlier runs (same recipe fingerprint, inputs and seed).")
        results = read_results(out_dir)
    todo = [j for j in jobs if j["hash"] not in done]
    spent = sum((r.get("spend", r.get("cost")) or 0) + (r.get("eval_cost") or 0)
                for r in results if not r.get("reused_from"))
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
        row = {k: j[k] for k in ("input", "recipe", "seed", "model", "fp", "hash")}
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

    def report(row):
        append_result(out_dir, row)
        status = (f"${row['cost']:.4f} · {row['latency_s']}s" if row["status"] == "success"
                  else f"ERROR {row['error']}")
        extra = f" ({'; '.join(row['steps'])})" if row.get("steps") else ""
        log(f"  {row['input']} · {row['recipe']} · s{row['seed']}: {status}{extra}")

    plain = [j for j in todo if not j.get("base_hash")]
    piped = [j for j in todo if j.get("base_hash")]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(one, plain):
            report(row)
    if piped:
        # plain results first, so pipelines can start from the very same base image
        bases = {}
        for d in [out_dir] + [d for d in history_dirs]:
            for r in read_results(d):
                if r.get("status") == "success" and not r.get("base_hash") and r.get("file") \
                        and os.path.exists(os.path.join(d, r["file"])):
                    bases.setdefault(r["hash"], (d, r["file"], r.get("url"), r.get("cost")))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for row in pool.map(lambda j: run_pipeline(j, b, out_dir, bases, lock_path), piped):
                report(row)
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
            b["_url_sha"][rec["url"]] = rec["sha1"]
