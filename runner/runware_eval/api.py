"""Thin Runware REST client: one task per request, polled until terminal.

One request per task (sent concurrently by the caller) keeps failures isolated: a provider error on
one task can turn a whole multi-task response into an error and hide the other results.
"""
import json
import os
import re
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


def _transient(exc):
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)) or (
        isinstance(exc, RunwareError) and re.search(r"HTTP (429|5\d\d)", str(exc)))


def _error_text(e):
    """The provider's own explanation is often in responseContent; keep it."""
    msg = e.get("message", "unknown error")
    extra = e.get("responseContent") or e.get("parameter")
    return f"{msg} {extra}".strip() if extra else msg


def _poll(uid, tries=4):
    """getResponse with retries on transient errors (polling never bills)."""
    for i in range(tries):
        try:
            return post([{"taskType": "getResponse", "taskUUID": uid}])
        except Exception as exc:  # noqa: BLE001
            if not _transient(exc) or i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def _submit(task, tries=3):
    """Submit once. On a transient failure, first ask whether the task exists (it may have been
    accepted before the error); re-submit only if Runware has no trace of it, so nothing bills twice."""
    for i in range(tries):
        try:
            return post([task])
        except Exception as exc:  # noqa: BLE001
            if not _transient(exc) or i == tries - 1:
                raise
            time.sleep(5 * (i + 1))
            try:
                data, errors = _poll(task["taskUUID"], tries=2)
                if data:
                    return data, errors
            except Exception:  # noqa: BLE001
                pass


def run_task(task, poll_every=3.0, max_wait=900):
    """Send one task and wait for a terminal result. Never re-sends a task Runware already has."""
    t0 = time.time()
    uid = task["taskUUID"]
    try:
        data, errors = _submit(task)
    except Exception as exc:  # noqa: BLE001  one task's failure must not stop a run
        return {"status": "error", "error": f"submit failed: {exc}", "latency_s": round(time.time() - t0, 1)}
    while True:
        err = next((e for e in errors if e.get("taskUUID") in (uid, None)), None)
        if err:
            return {"status": "error", "error": _error_text(err), "latency_s": round(time.time() - t0, 1)}
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
        try:
            data, errors = _poll(uid)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": f"polling failed: {exc}", "latency_s": round(time.time() - t0, 1)}


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
