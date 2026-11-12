"""Execute bench jobs: cached, budget-guarded, concurrent. Writes images, masks and results.jsonl."""
import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image

from . import api
from . import bench as benchmod
from . import video as video_mod
from .score import input_region, spent_on

MASK_MODEL = "runware:112@5"  # BiRefNet General
IDS = ("input", "recipe", "seed", "model", "fp", "hash")  # what names a result
OWN_OUTLINE = ("removeBackground", "imageMasking")


GRACE_S = 1800  # a task sent less than this long ago may still be running on Runware


class Budget:
    """Live spend guard. A task starts only if what is spent, what is in flight and its own cost fit the
    cap. Costs are learned during the run: in-flight and later tasks of a recipe count at the highest
    cost seen for it, and a recipe whose cost was never measured sends one task first and waits for
    its real cost before the rest start. What is left: a single task can pass the cap by its own
    cost minus its estimate."""

    def __init__(self, cap, spent, measured=()):
        self.cap, self.spent = cap, spent
        self.est, self.flying, self.known = {}, {}, set(measured)
        self.cond = threading.Condition()

    def _price(self, recipe):
        return self.est.get(recipe, 0.0)

    def take(self, recipe, est):
        with self.cond:
            self.est[recipe] = max(est or 0.0, self.est.get(recipe, 0.0))
            while recipe not in self.known and self.flying.get(recipe):
                self.cond.wait()
            reserved = sum(n * self._price(r) for r, n in self.flying.items())
            if self.spent + reserved + self._price(recipe) > self.cap + 1e-9:
                return False
            self.flying[recipe] = self.flying.get(recipe, 0) + 1
            return True

    def settle(self, recipe, actual):
        """`actual` None: the task died midway, so assume it was billed at the current estimate."""
        with self.cond:
            self.flying[recipe] -= 1
            self.spent += self._price(recipe) if actual is None else actual
            self.est[recipe] = max(self._price(recipe), actual or 0.0)
            self.known.add(recipe)
            self.cond.notify_all()


class Journal:
    """submitted.jsonl: every task sent, by content key, written before the request leaves. A later run
    asks Runware for that task's result before sending anything again."""

    def __init__(self, out_dir):
        self.path, self.lock, self.last = os.path.join(out_dir, "submitted.jsonl"), threading.Lock(), {}
        if os.path.exists(self.path):
            for line in open(self.path, encoding="utf8"):
                if line.strip():
                    r = json.loads(line)
                    self.last[r["key"]] = r

    def record(self, key, uid):
        row = {"key": key, "taskUUID": uid, "ts": time.time()}
        with self.lock:
            self.last[key] = row
            with open(self.path, "a", encoding="utf8") as f:
                f.write(json.dumps(row) + "\n")


def run_once(journal, key, task):
    """Run a task, unless an earlier run already sent the same one: then fetch that result instead.
    If it is still not ready and was sent recently, it is not sent again (that would bill twice)."""
    prev = journal.last.get(key) if journal else None
    if task.get("taskType") == api.SERVERLESS:
        prev = None  # a Serverless task is not in Runware's task store: nothing to fetch, it is called again
    if prev:
        age = time.time() - prev["ts"]
        res = api.poll_task(prev["taskUUID"], max_wait=min(300, max(0, GRACE_S - age)))
        if res["status"] == "success":
            return {**res, "taskUUID": prev["taskUUID"], "latency_s": None, "resumed": True}
        age = time.time() - prev["ts"]
        if res.get("pending") and age < GRACE_S:
            return {"status": "error", "taskUUID": prev["taskUUID"], "latency_s": None, "waiting": True,
                    "error": f"sent {age / 60:.0f} min ago and still running on Runware; not sent again. "
                             f"Run again in a few minutes (after {GRACE_S // 60} min it is sent anew)."}
    if journal:
        journal.record(key, task["taskUUID"])
    return api.run_task(task)


def read_results(out_dir):
    path = os.path.join(out_dir, "results.jsonl")
    if not os.path.exists(path):
        return []
    return [json.loads(line) for line in open(path, encoding="utf8") if line.strip()]


def append_result(out_dir, row):
    with open(os.path.join(out_dir, "results.jsonl"), "a", encoding="utf8") as f:
        f.write(json.dumps(row) + "\n")


def estimate(jobs, results):
    """Per-job new spend. Measured average for the recipe if it ever ran (any folder in `results`),
    else the price in the recipe's notes, else the model's highest listed price. A multi-step recipe
    whose first image comes from a plain recipe in the same batch only adds its `then` step."""
    measured = {}
    for r in results:
        if r.get("status") == "success" and r.get("cost") is not None and not r.get("base_hash"):
            measured.setdefault(r["recipe"], []).append(r["cost"])
    plain_hashes = {j["hash"] for j in jobs if not j.get("base_hash")} | {
        r["hash"] for r in results if r.get("status") == "success" and not r.get("base_hash")}
    rows, priced = [], {}
    for j in jobs:
        rec = j.get("_recipe") or {}
        if j["recipe"] in measured:
            cost, source = float(np.mean(measured[j["recipe"]])), "measured"
        else:
            if j["recipe"] not in priced:
                priced[j["recipe"]] = api.recipe_price(rec) if rec else api.listed_price(j["model"])
            cost, source = priced[j["recipe"]], "recipe notes / listed"
        if j.get("base_hash") and j["base_hash"] in plain_hashes:
            then = rec.get("then")
            cost = (api.recipe_price({"model": then["model"], "notes": ""}) if then else 0.0)
            source = "first image reused" + (" + then-step (listed)" if then else "")
        rows.append({**j, "est_cost": cost, "est_source": source})
    return rows


def mask_from(url, path, model=None):
    """Product mask (white = product) via background removal on Runware (`model`: an AIR, else MASK_MODEL)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    res = api.run_task({"taskType": "removeBackground", "taskUUID": str(uuid.uuid4()), "model": model or MASK_MODEL,
                        "inputs": {"image": url}, "outputFormat": "PNG", "includeCost": True})
    if res["status"] != "success":
        raise RuntimeError(f"Mask failed: {res.get('error')}")
    api.download(res["imageURL"], path + ".rgba.png")
    alpha = Image.open(path + ".rgba.png").split()[-1]
    Image.fromarray(((np.asarray(alpha) > 127) * 255).astype(np.uint8)).save(path)
    os.remove(path + ".rgba.png")
    return res.get("cost") or 0.0


def outline(row, source, out_dir):
    """Buy the product outline of an output (`source`: its URL or a data URI) for the outline checks.
    The cost goes on the row; a failure is noted and never loses the paid output."""
    try:
        row["eval_cost"] = mask_from(source, os.path.join(out_dir, "masks", row["file"].rsplit(".", 1)[0] + "_cut.png"))
    except RuntimeError as e:
        row["mask_error"] = str(e)


def data_uri(path):
    """A local picture as a data URI, for tasks on files that were never uploaded (video frames)."""
    import base64
    kind = "png" if path.lower().endswith(".png") else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(open(path, "rb").read()).decode()


def video_masks(video_path, out_dir, log=None):
    """Product outlines for a video output: one per sample frame (video.SAMPLES, spread from the first
    frame to the last), made like the outline of a picture output. The first frame's outline is also
    stored where the image checks look for it, so outline checks run on a video's first frame.
    Outlines that are already there are kept. Returns what was spent."""
    info = video_mod.ensure(video_path, out_dir, log)
    p = video_mod.paths(out_dir, video_path)
    todo = [k for k in (smp["k"] for smp in info.get("samples") or []) if not os.path.exists(p["mask"](k))]
    with ThreadPoolExecutor(max_workers=max(1, len(todo))) as pool:  # a few seconds each: all frames at once
        cost = sum(pool.map(lambda k: mask_from(data_uri(p["sample"](k)), p["mask"](k)), todo))
    if os.path.exists(p["mask"](0)) and not os.path.exists(p["first_mask"]):
        shutil.copyfile(p["mask"](0), p["first_mask"])
    return cost


def video_masks_missing(video_path, out_dir):
    p = video_mod.paths(out_dir, video_path)
    return any(not os.path.exists(p["mask"](smp["k"])) for smp in video_mod.ensure(video_path, out_dir).get("samples") or [])


def fill_video_masks(out_dir, budget, log=print, per_mask=0.001):
    """Video outputs that are in the folder without frame outlines (reused from an earlier run, or made
    before the runner bought them) get them now. The cost is added to the output's `eval_cost`."""
    rows = read_results(out_dir)
    def missing(r):
        try:
            return video_masks_missing(os.path.join(out_dir, r["file"]), out_dir)
        except Exception:  # noqa: BLE001  a file that is not a readable clip gets no outlines
            return False
    todo = [r for r in rows if r.get("status") == "success" and r.get("file") and video_mod.is_video(r["file"])
            and os.path.exists(os.path.join(out_dir, r["file"])) and missing(r)]
    if not todo:
        return
    est = len(todo) * video_mod.SAMPLES * per_mask
    if budget.spent + est > budget.cap + 1e-9:
        log(f"Frame outlines for {len(todo)} video output(s) not made: about ${est:.3f} would pass the cap.")
        return
    log(f"Making frame outlines for {len(todo)} video output(s) already in this folder ...")
    for r in todo:
        try:
            cost = video_masks(os.path.join(out_dir, r["file"]), out_dir)
            r["eval_cost"] = (r.get("eval_cost") or 0.0) + cost
            budget.spent += cost
            r.pop("mask_error", None)
        except Exception as e:  # noqa: BLE001
            r["mask_error"] = f"{type(e).__name__}: {e}"
    with open(os.path.join(out_dir, "results.jsonl"), "w", encoding="utf8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


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
    old, new = src["file"].rsplit(".", 1)[0], name.rsplit(".", 1)[0]
    for tail in ["_cut.png"] + [f"__f{k}_cut.png" for k in range(video_mod.SAMPLES)]:  # outline(s) of the output
        m_src = os.path.join(src_dir, "masks", old + tail)
        if os.path.exists(m_src):
            shutil.copyfile(m_src, os.path.join(out_dir, "masks", new + tail))
    row = {**src, **{k: j[k] for k in IDS},
           "file": name, "reused_from": os.path.abspath(src_dir), "eval_cost": 0.0}
    return row


def restore(cur_path, inp_path, region, featherPx, out_path):
    """Paste the original pixels of `region` back over the output, with a soft edge (no API call)."""
    orig = Image.open(inp_path).convert("RGB")
    W, H = orig.size
    cur = Image.open(cur_path).convert("RGB").resize((W, H), Image.BICUBIC)
    a = region.astype(np.float32)
    if featherPx:
        k = int(featherPx) * 2 + 1
        a = cv2.GaussianBlur(a, (k, k), featherPx / 2)
    a = a[..., None]
    comp = a * np.asarray(orig, np.float32) + (1 - a) * np.asarray(cur, np.float32)
    Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8)).save(out_path)
    return out_path


def transfer_detail(cur_path, inp_path, region, sigmaPx, featherPx, out_path):
    """Frequency separation: inside `region`, keep the output's lighting (low frequencies) and put back
    the original's fine detail (high frequencies: lettering, stitching). Local, no API call."""
    orig = np.asarray(Image.open(inp_path).convert("RGB"), np.float32)
    H, W = orig.shape[:2]
    cur = np.asarray(Image.open(cur_path).convert("RGB").resize((W, H), Image.BICUBIC), np.float32)
    blur = lambda x: cv2.GaussianBlur(x, (0, 0), sigmaPx)
    detail = blur(cur) + (orig - blur(orig))
    a = region.astype(np.float32)
    if featherPx:
        a = cv2.GaussianBlur(a, (0, 0), featherPx / 2)
    a = a[..., None]
    comp = a * detail + (1 - a) * cur
    Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8)).save(out_path)
    return out_path


def run_pipeline(j, b, out_dir, bases, lock_path, journal=None):
    """Base generation (reused when an identical plain recipe already produced it), then the recipe's
    `then` step (a second task on the first output) and `post` steps (local edits)."""
    r, inp = j["_recipe"], j["_inp"]
    row = {k: j[k] for k in IDS + ("base_hash",)}
    row.update(status="success", cost=0.0, spend=0.0, latency_s=0.0, steps=[])
    os.makedirs(os.path.join(out_dir, "steps"), exist_ok=True)
    stem_ = f"{j['input']}__{j['recipe']}__s{j['seed']}"
    if j["base_hash"] in bases:
        d, f, url, cost = bases[j["base_hash"]]
        cur_path, cur_url = os.path.join(d, f), url
        row["cost"] += cost or 0
        row["steps"].append(f"base reused from {f}")
    else:
        res = run_once(journal, j["base_hash"], j["task"])
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
        task = benchmod.then_task(then, ctx)
        res = run_once(journal, j["hash"] + ":then", task)
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
        if "transferDetail" in step:
            region = input_region(b, inp, step["transferDetail"])
            cur_path = transfer_detail(cur_path, os.path.join(b["_dir"], inp["path"]), region,
                                       step.get("sigmaPx", 6), step.get("featherPx", 6),
                                       os.path.join(out_dir, "steps", stem_ + "__post.png"))
            cur_url = None
            row["steps"].append(f"transfer detail {step['transferDetail']}")
        if "restore" in step:
            region = input_region(b, inp, step["restore"])
            cur_path = restore(cur_path, os.path.join(b["_dir"], inp["path"]), region, step.get("featherPx", 4),
                               os.path.join(out_dir, "steps", stem_ + "__post.png"))
            cur_url = None
            row["steps"].append(f"restore {step['restore']}")
    row["file"] = stem_ + os.path.splitext(cur_path)[1]
    shutil.copyfile(cur_path, os.path.join(out_dir, row["file"]))
    row["url"] = cur_url
    outline(row, pre_post_url, out_dir)  # post steps only touch small regions, so the pre-post image is used
    row["latency_s"] = round(row["latency_s"], 1)
    return row


def outdated(r, model_fps):
    """A result generated under an older record of its model (models.py). Rows with no stamp (made
    before the record existed) and models with no record today are left alone."""
    return bool(r.get("model_fp")) and model_fps.get(r.get("model")) not in (None, r["model_fp"])


def drop_outdated(out_dir, model_fps):
    """Take results generated under an older model record out of results.jsonl, so they are made again.
    Returns the dropped rows."""
    rows = read_results(out_dir)
    old = [r for r in rows if outdated(r, model_fps)]
    if old:
        gone = {id(r) for r in old}
        with open(os.path.join(out_dir, "results.jsonl"), "w", encoding="utf8") as f:
            for r in rows:
                if id(r) not in gone:
                    f.write(json.dumps(r) + "\n")
    return old


def execute(jobs, out_dir, maxSpend, workers=6, log=print, history_dirs=(), b=None, lock_path=None,
            model_fps=None, regenerate=False):
    """`model_fps`: {model: fingerprint of what Runware publishes about it today} (see models.py); every
    new result is stamped with it. `regenerate`: results stamped with an older fingerprint are made again."""
    os.makedirs(os.path.join(out_dir, "masks"), exist_ok=True)
    model_fps = model_fps or {}
    redo = {r["hash"] for r in drop_outdated(out_dir, model_fps)} if regenerate else set()
    if redo:
        log(f"Making {len(redo)} result(s) again: their model's published details changed since they were generated.")
    results = read_results(out_dir)
    done = {r["hash"] for r in results if r.get("status") == "success"
            and os.path.exists(os.path.join(out_dir, r["file"]))}
    past = {h: v for h, v in history([d for d in history_dirs if os.path.abspath(d) != os.path.abspath(out_dir)]).items()
            if not (regenerate and outdated(v[1], model_fps))}
    reused = 0
    for j in jobs:
        if j["hash"] not in done and j["hash"] in past:
            append_result(out_dir, reuse(j, *past[j["hash"]], out_dir))
            done.add(j["hash"])
            reused += 1
    if reused:
        log(f"Reused {reused} matching result(s) from earlier runs (same recipe fingerprint, inputs and draw).")
        results = read_results(out_dir)
    todo = [j for j in jobs if j["hash"] not in done]
    spent = spent_on(results)
    est = estimate(todo, results)
    unknown = [e["recipe"] for e in est if e["est_cost"] is None]
    projected = sum(e["est_cost"] or 0 for e in est)
    log(f"{len(jobs) - len(todo)} cached, {len(todo)} to run. Spent so far ${spent:.3f}, "
        f"projected ${projected:.3f}, cap ${maxSpend:.2f}.")
    if unknown:
        raise SystemExit(f"Stopped: no price known for {', '.join(sorted(set(unknown)))}. Add `price: <USD per "
                         "output>` to the recipe file (it does not change the fingerprint), so the cap can hold. "
                         "For a `model: auto` recipe, `routing.maxPrice` does the same and also binds the router.")
    if spent + projected > maxSpend:
        raise SystemExit(f"Stopped: ${spent + projected:.3f} would exceed the ${maxSpend:.2f} cap. "
                         "Raise budget.maxSpend in bench.yaml or run fewer recipes.")
    budget = Budget(maxSpend, spent, measured={e["recipe"] for e in est if e["est_source"] == "measured"})
    journal = Journal(out_dir)
    for h in redo:  # or the earlier task's result would be fetched instead of a new generation
        journal.last.pop(h, None)
    stamp = lambda row: {**row, "model_fp": model_fps[row["model"]]} if model_fps.get(row.get("model")) else row
    est_by = {e["hash"]: e["est_cost"] for e in est}
    frame_masks = ((b or {}).get("video") or {}).get("masks", True)

    def guarded(fn):
        """The projection above is an estimate; this holds the cap against what tasks really cost."""
        def wrapped(j):
            if not budget.take(j["recipe"], est_by.get(j["hash"])):
                return {**{k: j.get(k) for k in IDS}, "status": "error", "cost": None, "latency_s": None,
                        "not_started": True, "error": f"not started: it would pass the ${maxSpend:.2f} cap "
                                                      f"(${budget.spent:.3f} spent, costs ran above the estimate)"}
            actual = None
            try:
                row = stamp(fn(j))
                actual = (row.get("spend", row.get("cost")) or 0) + (row.get("eval_cost") or 0)
                return row
            finally:
                budget.settle(j["recipe"], actual)
        return wrapped

    def one(j):
        res = run_once(journal, j["hash"], j["task"])
        row = {k: j[k] for k in IDS}
        row.update(taskUUID=res.get("taskUUID") or j["task"]["taskUUID"], status=res["status"],
                   cost=res.get("cost"), latency_s=res.get("latency_s"), error=res.get("error"))
        if res.get("resumed"):
            row["resumed"] = True
        if res.get("seed") is not None:
            row["seed_used"] = res["seed"]  # the seed the model reports for this draw (none was asked for)
        if j["model"] == benchmod.ROUTER and res.get("model"):
            row["picked_model"] = res["model"]  # the response names the model the router chose
        row["task_type"] = j["task"].get("taskType")
        if res["status"] == "success":
            files = (res.get("outputs") or {}).get("files") or []
            url = (res.get("imageURL") or res.get("videoURL") or res.get("maskImageURL")
                   or (files[0]["url"] if files else None))
            if not url and isinstance(res.get("imageData"), str):
                # a Serverless endpoint answered with the picture itself (base64): there is no URL to keep
                import base64
                raw = base64.b64decode(res["imageData"])
                ext = ".png" if raw[:4] == b"\x89PNG" else ".webp" if raw[8:12] == b"WEBP" else ".jpg"
                row["file"] = f"{j['input']}__{j['recipe']}__s{j['seed']}{ext}"
                with open(os.path.join(out_dir, row["file"]), "wb") as f:
                    f.write(raw)
                if res.get("gpu_seconds") is not None:
                    row["gpu_seconds"] = res["gpu_seconds"]
                outline(row, data_uri(os.path.join(out_dir, row["file"])), out_dir)
                return row
            if not url and isinstance(res.get("text"), str):
                # caption and textInference answer with text, not a file: the text is the output
                row["file"] = f"{j['input']}__{j['recipe']}__s{j['seed']}.txt"
                with open(os.path.join(out_dir, row["file"]), "w", encoding="utf8") as f:
                    f.write(res["text"])
                row.update({k: res[k] for k in ("finishReason", "usage") if res.get(k) is not None})
                return row
            if not url:
                return {**row, "status": "error", "error": "no output URL or text in the response"}
            ext = os.path.splitext(url.split("?")[0])[1] or ".png"
            row["file"] = f"{j['input']}__{j['recipe']}__s{j['seed']}{ext}"
            row["url"] = url
            api.download(url, os.path.join(out_dir, row["file"]))
            # a product outline for the outline checks, made on Runware. Not for 3D and vector outputs (no
            # picture to cut), nor for cut-outs and masks: those are their own outline (see adapters.py)
            if ext.lower() in (".png", ".jpg", ".jpeg", ".webp") and row["task_type"] not in OWN_OUTLINE:
                outline(row, url, out_dir)
            elif video_mod.is_video(row["file"]) and frame_masks:
                # the same for a clip: an outline for each sample frame (see video_masks)
                try:
                    row["eval_cost"] = video_masks(os.path.join(out_dir, row["file"]), out_dir)
                except Exception as e:  # noqa: BLE001  a clip that cannot be read or outlined is still a paid output
                    row["mask_error"] = f"{type(e).__name__}: {e}"
        return row

    def report(row):
        append_result(out_dir, row)
        took = "fetched from an earlier run" if row.get("resumed") else f"{row['latency_s']}s"
        status = (f"${row['cost'] or 0:.4f} Â· {took}" if row["status"] == "success"
                  else f"ERROR {row['error']}")
        extra = f" ({'; '.join(row['steps'])})" if row.get("steps") else ""
        log(f"  {row['input']} Â· {row['recipe']} Â· s{row['seed']}: {status}{extra}")

    def safe(fn):
        def wrapped(j):
            try:
                return fn(j)
            except Exception as exc:  # noqa: BLE001  one output's failure must not stop the run
                return {**{k: j.get(k) for k in IDS},
                        "status": "error", "error": f"{type(exc).__name__}: {exc}", "cost": None, "latency_s": None}
        return wrapped

    plain = [j for j in todo if not j.get("base_hash")]
    piped = [j for j in todo if j.get("base_hash")]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(safe(guarded(one)), plain):
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
            for row in pool.map(safe(guarded(lambda j: run_pipeline(j, b, out_dir, bases, lock_path, journal))), piped):
                report(row)
    if frame_masks:
        fill_video_masks(out_dir, budget, log)
    return read_results(out_dir)


def prepare_offline(b, out_dir):
    """For commands that only read results (score, report, label, calibrate, metric controls): no uploads.
    `auto:` masks are taken from the run folder; only a missing one needs a Runware login to generate."""
    missing = []
    for inp in b["inputs"]:
        name = os.path.splitext(os.path.basename(inp["path"]))[0]
        for rname, spec in (inp.get("regions") or {}).items():
            if isinstance(spec, str) and spec.startswith("auto:"):
                target = os.path.join(out_dir, "masks", f"{name}_{rname}.png")
                if os.path.exists(target):
                    inp["regions"][rname] = os.path.abspath(target)
                else:
                    missing.append(f"{name}:{rname}")
    if missing:
        try:
            api.api_key()
        except api.RunwareError:
            raise ValueError(f"Mask(s) {', '.join(missing)} are generated on Runware and not in this run folder yet. "
                             "Sign in once with `runware auth login`, or give the masks as files in bench.yaml.")
        benchmod.ensure_media(b, os.path.join(out_dir, "media.lock.json"))
        ensure_input_masks(b, out_dir)


def ensure_input_masks(b, out_dir):
    """Resolve `regions.<name>: auto:<AIR>` into mask files once."""
    for inp in b["inputs"]:
        for name, spec in (inp.get("regions") or {}).items():
            if isinstance(spec, str) and spec.startswith("auto:"):
                target = os.path.join(out_dir, "masks", f"{os.path.splitext(os.path.basename(inp['path']))[0]}_{name}.png")
                if not os.path.exists(target):
                    mask_from(inp["_url"], target, spec[len("auto:"):].strip() or None)
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
