"""Offline tests of the budget guard and the resume logic: the Runware API is replaced by fakes."""
import json
import os
import tempfile
import time

from runware_eval import api, run

from harness import check, finish

REAL_POLL, REAL_RUN = api.poll_task, api.run_task


def job(i, recipe="r", est=None):
    return {"input": "in", "recipe": recipe, "seed": i, "model": "m:1@1", "fp": "fp", "hash": f"h{recipe}{i}",
            "task": {"taskType": "videoInference", "taskUUID": f"u-{recipe}-{i}", "model": "m:1@1"}}


sent = []
run.api.download = lambda url, path: open(path, "wb").write(b"x")
run.estimate = lambda jobs, results: [{**j, "est_cost": 0.02, "est_source": "test"} for j in jobs]

# 1. costs run 3x above the estimate: the cap must hold while running
def fake_run(task, **kw):
    sent.append(task["taskUUID"])
    time.sleep(0.02)
    return {"status": "success", "videoURL": "http://x/a.mp4", "cost": 0.06, "latency_s": 1.0, "taskUUID": task["taskUUID"]}
run.api.run_task = fake_run
d = tempfile.mkdtemp()
rows = run.execute([job(i) for i in range(20)], d, maxSpend=0.50, log=lambda *a: None)
spend = sum(r.get("cost") or 0 for r in rows)
check("cap holds when real cost is 3x the estimate", spend <= 0.50 + 1e-9, f"spent ${spend:.2f} of $0.50, {len(sent)} of 20 sent")
check("tasks that did not start are recorded", sum(1 for r in rows if r.get("not_started")) == 20 - len(sent))
check("estimate alone would have allowed all 20 (old behaviour: $1.20)", 20 * 0.02 <= 0.50)
sent.clear()
jobs2 = [job(i, "cheap") for i in range(6)] + [job(i, "dear") for i in range(6)]
run.api.run_task = lambda task, **kw: (sent.append(task["taskUUID"]), time.sleep(0.02), {"status": "success", "videoURL": "http://x/a.mp4",
    "cost": 0.5 if "dear" in task["taskUUID"] else 0.01, "latency_s": 1.0})[2]
rows = run.execute(jobs2, tempfile.mkdtemp(), maxSpend=1.20, log=lambda *a: None)
spend = sum(r.get("cost") or 0 for r in rows)
check("two recipes, one 25x its estimate: cap holds, cheap one completes", spend <= 1.20 + 1e-9 and sum(1 for u in sent if "cheap" in u) == 6, f"spent ${spend:.2f} of $1.20")
run.api.run_task = fake_run

# 2. unknown price stops the run
run.estimate = lambda jobs, results: [{**j, "est_cost": None, "est_source": "test"} for j in jobs]
try:
    run.execute([job(0, "nop")], tempfile.mkdtemp(), maxSpend=1, log=lambda *a: None)
    check("unknown price stops the run", False)
except SystemExit as e:
    check("unknown price stops the run", "`price:" in str(e))
check("price is read from the recipe", api.recipe_price({"price": 0.4, "notes": "saves $9", "model": "x"}) == 0.4)
from runware_eval import bench as _bench
check("budget.maxSpend is the run's cap", _bench.maxSpend({"budget": {"maxSpend": 3}}) == 3)
check("no budget, no cap", _bench.maxSpend({}) is None)
run.estimate = lambda jobs, results: [{**j, "est_cost": 0.02, "est_source": "test"} for j in jobs]

# 3. interrupted run: the task was sent, the process died before the result was saved
d = tempfile.mkdtemp()
sent.clear()
j = job(1, "vid")
run.Journal(d).record(j["hash"], "u-first")
polled = []
def fake_poll_ready(uid, max_wait=0, **kw):
    polled.append(uid)
    return {"status": "success", "videoURL": "http://x/a.mp4", "cost": 0.30, "taskUUID": uid}
run.api.poll_task = fake_poll_ready
rows = run.execute([j], d, maxSpend=5, log=lambda *a: None)
check("re-run fetches the earlier task instead of sending again", sent == [] and polled == ["u-first"] and rows[-1]["status"] == "success"
      and rows[-1]["taskUUID"] == "u-first" and rows[-1].get("resumed"))

# 4. earlier task still running, sent recently: do not send again
d = tempfile.mkdtemp()
sent.clear()
run.Journal(d).record(j["hash"], "u-first")
run.api.poll_task = lambda uid, max_wait=0, **kw: {"status": "error", "error": "timed out", "pending": True}
rows = run.execute([j], d, maxSpend=5, log=lambda *a: None)
check("still running and recent: not sent again", sent == [] and rows[-1]["status"] == "error" and "not sent again" in rows[-1]["error"])

# 5. earlier task older than the grace period and no result: send anew
d = tempfile.mkdtemp()
sent.clear()
open(os.path.join(d, "submitted.jsonl"), "w").write(json.dumps({"key": j["hash"], "taskUUID": "u-old", "ts": time.time() - 7200}) + "\n")
rows = run.execute([j], d, maxSpend=5, log=lambda *a: None)
check("older than the grace period: sent anew, once", sent == ["u-vid-1"] and rows[-1]["status"] == "success")
last = [json.loads(l) for l in open(os.path.join(d, "submitted.jsonl"))][-1]
check("the new submission is journaled", last["taskUUID"] == "u-vid-1")

# 6. earlier task failed on Runware: send anew
d = tempfile.mkdtemp()
sent.clear()
run.Journal(d).record(j["hash"], "u-first")
run.api.poll_task = lambda uid, max_wait=0, **kw: {"status": "error", "error": "provider error"}
rows = run.execute([j], d, maxSpend=5, log=lambda *a: None)
check("earlier task failed: sent anew", sent == ["u-vid-1"])

# 7. api.poll_task against a fake transport
calls = []
def fake_post(tasks, timeout=180):
    calls.append(tasks[0])
    return ([{"taskUUID": tasks[0]["taskUUID"], "status": "processing"}], []) if len(calls) < 3 else \
           ([{"taskUUID": tasks[0]["taskUUID"], "status": "success", "videoURL": "http://x"}], [])
api.post = fake_post
api.poll_task = REAL_POLL
r = api.poll_task("abc", max_wait=0)
check("poll_task: one poll, pending when not ready", r.get("pending") and len(calls) == 1 and calls[0]["taskType"] == "getResponse")
r = api.poll_task("abc", max_wait=5, poll_every=0.01)
check("poll_task: returns the result when it arrives", r["status"] == "success" and all(c["taskType"] == "getResponse" for c in calls))

# 8. run_task sends async, backs off on 429 without polling, never re-sends after a dropped connection
log = []
state = {"n": 0}
def post_429(tasks, timeout=180):
    log.append(tasks[0])
    if tasks[0]["taskType"] != "getResponse":
        state["n"] += 1
        if state["n"] == 1:
            err = api.NotAccepted("HTTP 429 from Runware")
            err.retry_after = 0.01
            raise err
        return [{"taskType": tasks[0]["taskType"], "taskUUID": tasks[0]["taskUUID"]}], []
    return [{"taskUUID": tasks[0]["taskUUID"], "status": "success", "imageURL": "http://x/a.jpg", "cost": 0.01}], []
api.post, api.run_task = post_429, REAL_RUN
r = api.run_task({"taskType": "imageInference", "taskUUID": "t1", "model": "m"}, poll_every=0.01)
subs = [t for t in log if t["taskType"] != "getResponse"]
check("run_task: async delivery on every send", all(t.get("deliveryMethod") == "async" for t in subs))
check("run_task: 429 is sent again, then succeeds", len(subs) == 2 and r["status"] == "success")
log.clear()
def post_drop(tasks, timeout=180):
    log.append(tasks[0])
    if tasks[0]["taskType"] != "getResponse":
        raise TimeoutError("connection dropped")
    return [{"taskUUID": tasks[0]["taskUUID"], "status": "success", "imageURL": "http://x/a.jpg", "cost": 0.01}], []
api.post = post_drop
r = api.run_task({"taskType": "imageInference", "taskUUID": "t2", "model": "m"}, poll_every=0.01)
check("run_task: dropped connection is polled, not sent twice",
      len([t for t in log if t["taskType"] != "getResponse"]) == 1 and r["status"] == "success")
log.clear()
def post_provider_error(tasks, timeout=180):
    if tasks[0]["taskType"] == "getResponse":
        return [], [{"taskUUID": tasks[0]["taskUUID"], "message": "bria responded with HTTP 422", "status": "error"}]
    return [{"taskUUID": tasks[0]["taskUUID"]}], []
api.post = post_provider_error
r = api.run_task({"taskType": "imageInference", "taskUUID": "t3", "model": "m"}, poll_every=0.01)
check("run_task: provider error from polling is reported", r["status"] == "error" and "422" in r["error"])

finish()
