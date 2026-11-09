"""Thin Runware REST client: one task per request, polled until terminal.

One request per task (sent concurrently by the caller) keeps failures isolated: a provider error on
one task can turn a whole multi-task response into an error and hide the other results.
"""
import json
import os
import time
import urllib.error
import urllib.request

import yaml

API = "https://api.runware.ai/v1"
UA = "runware-eval/0.1"


class RunwareError(Exception):
    pass


def api_key():
    """RUNWARE_API_KEY, else the Runware CLI login. Never printed, never written."""
    key = os.environ.get("RUNWARE_API_KEY")
    if key:
        return key
    path = os.path.expanduser("~/.runware/config.yaml")
    if os.path.exists(path):
        key = (yaml.safe_load(open(path, encoding="utf8")) or {}).get("api_key")
        if key:
            return key
    raise RunwareError("No Runware login found. Run `runware auth login` in a terminal, "
                       "or set RUNWARE_API_KEY.")


def post(tasks, timeout=180):
    req = urllib.request.Request(API, data=json.dumps(tasks).encode(), method="POST", headers={
        "Authorization": f"Bearer {api_key()}", "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except ValueError:
            raise RunwareError(f"HTTP {e.code} from Runware")
    return body.get("data", []), body.get("errors", [])


def run_task(task, poll_every=3.0, max_wait=900):
    """Send one task and wait for a terminal result. Never re-sends: a re-send would bill twice."""
    t0 = time.time()
    data, errors = post([task])
    uid = task["taskUUID"]
    while True:
        err = next((e for e in errors if e.get("taskUUID") in (uid, None)), None)
        if err:
            return {"status": "error", "error": err.get("message", "unknown error"),
                    "latency_s": round(time.time() - t0, 1)}
        item = next((d for d in data if d.get("taskUUID") == uid), None)
        if item and item.get("status") not in ("processing", "pending") and any(
                k in item for k in ("imageURL", "videoURL", "audioURL", "text", "outputs")):
            return {"status": "success", **item, "latency_s": round(time.time() - t0, 1)}
        if item and item.get("status") == "error":
            return {"status": "error", "error": item.get("error", "task failed"),
                    "latency_s": round(time.time() - t0, 1)}
        if time.time() - t0 > max_wait:
            return {"status": "error", "error": f"timed out after {max_wait}s",
                    "latency_s": round(time.time() - t0, 1)}
        time.sleep(poll_every)
        data, errors = post([{"taskType": "getResponse", "taskUUID": uid}])


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


_INDEX = None


def model_schema(air):
    """Public JSON Schema for a model AIR (cached). Used for listed prices and task types."""
    global _INDEX
    if _INDEX is None:
        req = urllib.request.Request("https://runware.ai/docs/models/index.json", headers={"User-Agent": UA})
        _INDEX = json.load(urllib.request.urlopen(req, timeout=60))
    entry = next((m for m in _INDEX if m.get("air") == air), None)
    if not entry:
        return None
    req = urllib.request.Request(entry["schema"], headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=60))


def listed_price(air):
    """Highest listed price per output for a model, as a conservative estimate. None if unknown."""
    try:
        s = model_schema(air)
    except (urllib.error.URLError, ValueError):
        return None
    p = (s or {}).get("info", {}).get("x-pricing", {})
    prices = [r["amount"] for r in p.get("rates", []) if isinstance(r.get("amount"), (int, float))]
    prices += [e["price"] for e in p.get("examples", []) if isinstance(e.get("price"), (int, float))]
    return max(prices) if prices else None


def recipe_price(recipe):
    """Price per output for a recipe with no measured runs: the first `$x` in its notes (written by
    whoever set the recipe up, tier-specific), else the highest price in the model's schema."""
    import re
    m = re.search(r"\$\s?(\d+(?:\.\d+)?)", recipe.get("notes") or "")
    return float(m.group(1)) if m else listed_price(recipe["model"])
