"""Offline tests of `model: auto` recipes (Runware's Model Router): the request, the cache key per
seed, the price estimate, the recorded pick and the report rows. The Runware API is replaced by fakes."""
import os
import sys
import tempfile

from runware_eval import api, bench, recipes, report, run

ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, extra)


def make_bench(router):
    inp = {"path": "in/a.jpg", "_url": "http://m/a.jpg", "_size": (1000, 1500)}
    named = [{"id": "one", "model": "x:1@1", "params": {"positivePrompt": "p", "seed": "$seed"}},
             {"id": "two", "model": "y:2@1", "params": {"positivePrompt": "p", "seed": "$seed"}}]
    return {"_dir": ".", "_url_sha": {"http://m/a.jpg": "abc"}, "inputs": [inp], "seeds": [1, 2, 3],
            "recipes": named + [router]}


router = {"id": "router", "model": "auto", "routing": {"allowedModels": "bench", "preferences": {"quality": 5}},
          "params": {"positivePrompt": "p", "inputs": {"referenceImages": ["$input"]}}}
b = make_bench(router)
jobs = [j for j in bench.jobs(b, "full") if j["recipe"] == "router"]
t = jobs[0]["task"]
check("the task goes out as model auto with a routing block", t["model"] == "auto" and "routing" in t)
check("`allowedModels: bench` becomes the bench's other models", t["routing"]["allowedModels"] == ["x:1@1", "y:2@1"])
check("preferences are passed through", t["routing"]["preferences"] == {"quality": 5})
check("each seed is its own draw (no seed in the request, three cache keys)",
      len({j["hash"] for j in jobs}) == 3 and "seed" not in t)
check("the same seed keeps its key between runs",
      [j["hash"] for j in jobs] == [j["hash"] for j in bench.jobs(b, "full") if j["recipe"] == "router"])

try:
    bench.jobs(make_bench({**router, "post": [{"restore": "logo"}]}), "full")
    check("then/post on a router recipe is refused", False)
except ValueError as err:
    check("then/post on a router recipe is refused", "auto" in str(err))

lone = make_bench(router)
lone["recipes"] = lone["recipes"][1:]
try:
    bench.jobs(lone, "full")
    check("`allowedModels: bench` needs two other models", False)
except ValueError as err:
    check("`allowedModels: bench` needs two other models", "at least two" in str(err))

b["maxModels"] = 2
check("the router does not count towards maxModels", len(bench.jobs(b, "full")) == 9)
b["maxModels"] = 1
try:
    bench.jobs(b, "full")
    check("maxModels limits the named models", False)
except ValueError as err:
    check("maxModels limits the named models", "maxModels is 1" in str(err))
del b["maxModels"]

check("a fingerprint from before the settings were renamed still holds", recipes.fingerprint(
    {"model": "x:1@1", "params": {"a": 1}, "size": {"multiple": 16, "maxMp": 4.0},
     "post": [{"transferDetail": "logo", "sigmaPx": 6, "featherPx": 6}]}) == "7c72a1950bcf7381")
check("routing changes the fingerprint",
      recipes.fingerprint(router) != recipes.fingerprint({**router, "routing": {"allowedModels": "bench"}}))
check("a recipe without routing keeps its fingerprint", recipes.fingerprint(
    {"model": "x:1@1", "params": {"a": 1}}) == recipes.fingerprint({"model": "x:1@1", "params": {"a": 1}, "notes": "n"}))

check("price: the recipe's own price first", api.recipe_price({**router, "price": 0.08}) == 0.08)
check("price: else the router's own ceiling",
      api.recipe_price({"model": "auto", "routing": {"maxPrice": 0.05}, "notes": "about $9"}) == 0.05)
check("price: unknown without either (the run then stops and asks)", api.recipe_price(router) is None)

# the run records the model the response names
run.api.download = lambda url, path: open(path, "wb").write(b"x")
run.mask_from = lambda url, path: 0.0
run.estimate = lambda jobs, results: [{**j, "est_cost": 0.02, "est_source": "test"} for j in jobs]
picks = iter(["x:1@1", "y:2@1", "x:1@1"])
run.api.run_task = lambda task, **kw: {"status": "success", "imageURL": "http://x/a.jpg", "cost": 0.01,
                                       "latency_s": 1.0, "taskUUID": task["taskUUID"],
                                       "model": next(picks) if task["model"] == "auto" else task["model"]}
d = tempfile.mkdtemp()
rows = run.execute(jobs, d, maxSpend=1, workers=1, log=lambda *a: None)
check("the pick is recorded per call", [r.get("picked_model") for r in rows] == ["x:1@1", "y:2@1", "x:1@1"])
named_rows = run.execute([j for j in bench.jobs(b, "full") if j["recipe"] == "one"], tempfile.mkdtemp(), maxSpend=1,
                         log=lambda *a: None)
check("named recipes record no pick", all("picked_model" not in r for r in named_rows))

# report rows
gate = lambda p: {"mode": "gate", "dimension": "d", "label": "L", "status": "ok", "values": {"value": 1.0},
                  "thresholds": {"min": 0.5}, "pass": p}
item = lambda rid, seed, pick, p: {"recipe": rid, "seed": seed, "input": "a", "picked_model": pick, "metrics": [gate(p)]}
agg = {"router": {"items": [item("router", 1, "x:1@1", False), item("router", 2, "y:2@1", True),
                            item("router", 3, "x:1@1", False)], "fails": 1, "checks": 1},
       "one": {"items": [], "fails": 1, "checks": 1}, "two": {"items": [], "fails": 0, "checks": 1}}
order = ["two", "one", "router"]
rr = report.router_rows(agg, order, {r["id"]: r for r in b["recipes"]}, [{"recipe": "router"}], "two")
x = rr[0]
check("report: picks counted, most frequent first", x["picks"] == [("x:1@1", 2), ("y:2@1", 1)])
check("report: failed checks per pick", x["by_pick"] == {"x:1@1": [1, 1], "y:2@1": [0]})
check("report: place, failed calls and the best recipe's model", (x["place"], x["failed_calls"], x["best_model"]) == (3, 1, "y:2@1"))
check("report: the same model called by name is linked", x["by_name"] == {"y:2@1": ["two"], "x:1@1": ["one"]})
html = report.router_section(rr, agg, order, {r["id"]: r for r in b["recipes"]}, "two", lambda h, i="": f"<h2>{h}</h2>{i}")
check("report: section says how often the router chose the best recipe's model",
      "chose that model on 1 of 3 calls" in html and "2 different models" in html)
check("report: no section without router recipes", report.router_section([], agg, order, {}, "two", None) == "")

sys.exit(0 if ok else 1)
