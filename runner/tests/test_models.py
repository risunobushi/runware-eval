"""Parameter check against a model's schema, and the record of what a model publishes. No network."""
import copy
import json
import os
import tempfile

from runware_eval import api, models, run

from harness import check, finish

def doc(status="live", price=0.02, steps_default=16, extra_field=False):
    props = {
        "taskType": {"type": "string", "const": "imageInference"}, "taskUUID": {"type": "string"},
        "model": {"type": "string", "const": "test:1@1"}, "includeCost": {"type": "boolean"},
        "positivePrompt": {"type": "string"}, "promptExtend": {"type": "boolean", "default": True},
        "width": {"type": "integer", "minimum": 128, "maximum": 2048},
        "steps": {"type": "integer", "minimum": 1, "maximum": 50, "default": steps_default},
        "resolution": {"type": "string", "enum": ["1k", "2k"]},
        "layers": {"type": "boolean"},
        "inputs": {"type": "object", "additionalProperties": False,
                   "properties": {"referenceImages": {"type": "array", "items": {"type": "string"}}}},
    }
    if extra_field:
        props["seed"] = {"type": "integer"}
    item = {"type": "object", "additionalProperties": False, "properties": props,
            "required": ["taskType", "taskUUID", "model", "positivePrompt"],
            "allOf": [{"if": {"required": ["resolution"]}, "then": {"required": ["layers"]}}]}
    return {"info": {"x-status": status, "version": "1.0.0",
                     "x-pricing": {"measured": [{"configuration": "1024x1024", "price": price}]}},
            "components": {"schemas": {"RequestBody": {"type": "array", "items": item}}}}


task = {"taskType": "imageInference", "taskUUID": "u", "model": "test:1@1", "includeCost": True,
        "positivePrompt": "a bag", "width": 1024, "inputs": {"referenceImages": ["https://x/a.png"]}}

# 1. the parameter check
check("a valid request has no problems", models.check_task(task, doc()) == [])
got = models.check_task({**task, "promptExtned": False}, doc())
check("a misspelt field stops, with the field it probably meant",
      got and got[0][0] == "stop" and "promptExtned" in got[0][1] and "promptExtend" in got[0][1], got)
got = models.check_task({**task, "inputs": {"referenceImage": ["https://x/a.png"]}}, doc())
check("a misspelt nested field stops, named with its path",
      got and got[0][0] == "stop" and "inputs.referenceImage" in got[0][1], got)
got = models.check_task({**task, "width": 4096}, doc())
check("a value out of range stops", got and got[0][0] == "stop" and "width" in got[0][1] and "2048" in got[0][1], got)
got = models.check_task({**task, "resolution": "4k", "layers": True}, doc())
check("a value outside the allowed set stops and lists the set",
      got and got[0][0] == "stop" and "1k, 2k" in got[0][1], got)
no_prompt = {k: v for k, v in task.items() if k != "positivePrompt"}
got = models.check_task(no_prompt, doc())
check("a field the schema calls required only warns", got and {g[0] for g in got} == {"warn"}, got)
got = models.check_task({**task, "resolution": "2k"}, doc())
check("a conditional rule only warns", got and {g[0] for g in got} == {"warn"}, got)
check("no schema: not checked", models.check_task(task, None) is None)

models._DOCS.update({"test:1@1": doc(), "nowhere:1@1": None})
jobs = [{"recipe": "good", "seed": 1, "task": task, "_recipe": {}, "_inp": {}},
        {"recipe": "good", "seed": 2, "task": {**task, "oops": 1}, "_recipe": {}, "_inp": {}},  # only one request per recipe
        {"recipe": "typo", "seed": 1, "task": {**task, "stepz": 4}, "_recipe": {}, "_inp": {}},
        {"recipe": "unlisted", "seed": 1, "task": {**task, "model": "nowhere:1@1"}, "_recipe": {}, "_inp": {}},
        {"recipe": "routed", "seed": 1, "task": {**task, "model": "auto", "anything": 1}, "_recipe": {}, "_inp": {}}]
problems, unchecked = models.check_jobs(jobs)
check("check_jobs: one request per recipe, the typo is found", list(problems) == ["typo"] and problems["typo"]["stop"], problems)
check("check_jobs: a model with no schema is reported as not checked, the router is left out", unchecked == ["unlisted"], unchecked)

# 2. snapshots and what changed
a = models.snapshot("test:1@1", doc())
check("the same published details give the same fingerprint", a["fp"] == models.snapshot("test:1@1", doc())["fp"])
b = models.snapshot("test:1@1", doc(status="deprecated", price=0.03, steps_default=8, extra_field=True))
what = models.diff(a, b)
check("a changed model has another fingerprint", a["fp"] != b["fp"])
check("status change is named", any("live → deprecated" in w for w in what), what)
check("price change is named", any("$0.02 → $0.03" in w for w in what), what)
check("a new field is named", any(w.startswith("field added") and "seed" in w for w in what), what)
check("a moved default is named", any("default of steps: 16 → 8" in w for w in what), what)
rules = copy.deepcopy(doc())
rules["components"]["schemas"]["RequestBody"]["items"]["allOf"] = []
check("a change only in the conditional rules is still a change",
      models.diff(a, models.snapshot("test:1@1", rules)) == ["the rules between fields changed (which fields need or exclude each other)"])

# 3. the record in the run folder, and results made under an older record
tmp = tempfile.mkdtemp()
smoke, full = os.path.join(tmp, "smoke"), os.path.join(tmp, "full")
models._DOCS["test:1@1"] = doc()
today, changed = models.changes(["test:1@1", "auto"], [smoke, full])
check("first run: nothing to compare with, nothing changed", changed == {} and list(today) == ["test:1@1"])
models.record(smoke, today, changed)
today2, changed2 = models.changes(["test:1@1"], [smoke, full])
check("same details on the next run: no change", changed2 == {})
models._DOCS["test:1@1"] = doc(price=0.03)
today3, changed3 = models.changes(["test:1@1"], [smoke, full])
check("a change is found against the record of another run folder",
      list(changed3) == ["test:1@1"] and any("price" in w for w in changed3["test:1@1"]["what"]), changed3)
old_fp, new_fp = today["test:1@1"]["fp"], today3["test:1@1"]["fp"]
models.record(full, {"test:1@1": {**today["test:1@1"]}})
hist = models.record(full, today3, changed3)
check("the record keeps both snapshots and what changed",
      [x["fp"] for x in hist["test:1@1"]] == [old_fp, new_fp] and hist["test:1@1"][-1]["changed"])
rows = [{"hash": "h-old", "model": "test:1@1", "model_fp": old_fp, "recipe": "r"},
        {"hash": "h-new", "model": "test:1@1", "model_fp": new_fp, "recipe": "r"},
        {"hash": "h-unstamped", "model": "test:1@1", "recipe": "r"}]
st = models.stale(rows, full)
check("only the result stamped with the older record is marked", list(st) == ["h-old"] and "price" in st["h-old"]["what"][0], st)

# 4. execute: results are stamped, and --regenerate-changed makes outdated ones again
run.api.download = lambda url, path: open(path, "wb").write(b"x")
run.estimate = lambda jobs, results: [{**j, "est_cost": 0.02, "est_source": "test"} for j in jobs]
run.mask_from = lambda url, path, model=None: 0.0
sent = []


def fake_run(t, **kw):
    sent.append(t["taskUUID"])
    return {"status": "success", "imageURL": f"http://x/{len(sent)}.png", "cost": 0.02, "latency_s": 1.0}


run.api.run_task = fake_run
run.api.poll_task = lambda uid, max_wait=0, **kw: {"status": "success", "imageURL": "http://x/old.png", "cost": 0.02}
out = os.path.join(tmp, "exec")
os.makedirs(out)
J = [{"input": "a", "recipe": "r", "seed": n, "model": "test:1@1", "fp": "f", "hash": f"h{n}", "base_hash": None,
      "task": {"taskUUID": f"t{n}", "taskType": "imageInference"}} for n in (1, 2)]
quiet = lambda *a: None
res = run.execute(J, out, 1.0, log=quiet, model_fps={"test:1@1": old_fp})
check("new results carry the model fingerprint", [r.get("model_fp") for r in res] == [old_fp, old_fp] and len(sent) == 2)
res = run.execute(J, out, 1.0, log=quiet, model_fps={"test:1@1": new_fp})
check("a changed model alone does not spend: cached results are kept", len(sent) == 2 and [r["model_fp"] for r in res] == [old_fp] * 2)
res = run.execute(J, out, 1.0, log=quiet, model_fps={"test:1@1": new_fp}, regenerate=True)
check("--regenerate-changed makes them again, as new tasks", len(sent) == 4 and [r["model_fp"] for r in res] == [new_fp] * 2, (len(sent), res))
check("the outdated rows are gone from results.jsonl", len(run.read_results(out)) == 2)
res = run.execute(J, out, 1.0, log=quiet, model_fps={"test:1@1": new_fp}, regenerate=True)
check("and a second time nothing is sent", len(sent) == 4)

finish()
