"""Requirements and checks: what stops a run, yes/no judge checks, and the table the user chooses from."""
import sys

from runware_eval import catalog, score

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILED.append(name)


def bench(reqs):
    return {"requirements": reqs, "evaluate": {
        "pixel_shift": {"metrics": [{"id": "mask_iou", "region": "product", "min": 0.9, "label": "Outline"},
                                     {"id": "ssim_region", "region": "product", "label": "Structure"}]},
        "prompt_adherence": {"metrics": [{"id": "vlm_checklist", "label": "Real photo (judges)",
                                          "questions": ["Does image 2 look like a real photograph?"]}]}}}


full = [{"need": "Same outline", "checks": ["Outline"]}, {"need": "Same structure", "checks": ["Structure"]},
        {"need": "Reads as a real photograph", "checks": ["Real photo (judges)"]}]
rows, warn = score.coverage(bench(full))
st = {r["need"]: r["status"] for r in rows}
check("a yes/no judge check counts as a limit by itself", st["Reads as a real photograph"] == "limit", st)
check("a number with no limit is still only measured", st["Same structure"] == "measured")
check("nothing here stops a run", score.coverage_errors(bench(full)) == [])

hole = full + [{"need": "Nothing was added", "checks": []}]
check("a requirement with no check stops a run", score.coverage_errors(bench(hole)) == ["nothing measures: Nothing was added"])
wrong = full + [{"need": "Nothing was added", "checks": ["Extras"]}]
check("so does a requirement naming a check that does not exist", len(score.coverage_errors(bench(wrong))) == 2)
chosen = full + [{"need": "Nothing was added", "checks": [], "notMeasured": "dropped by the user: judged by eye"}]
rows, warn = score.coverage(bench(chosen))
check("left out by the user's choice: listed, and does not stop a run",
      score.coverage_errors(bench(chosen)) == [] and rows[-1]["status"] == "dropped" and any("left out by choice" in w for w in warn))

q = {"id": "vlm_checklist", "questions": ["a", "b"]}
check("yes on every question passes", score.check({"value": 0.83, "yes": True}, q) is True)
check("no on one question fails, whatever the share of yes answers", score.check({"value": 0.83, "yes": False}, q) is False)
check("an explicit min from an older bench is still used", score.check({"value": 0.83, "yes": False}, {**q, "min": 0.8}) is True)
check("a rubric score without a limit has no verdict", score.check({"value": 4.0}, {"id": "vlm_rubric"}) is None)

b = bench(full)
plan = score.plan(b, catalog.load())
by = {r["label"]: r for r in plan}
check("the plan lists every check with its requirement", [r["label"] for r in plan] == ["Outline", "Structure", "Real photo (judges)"]
      and by["Outline"]["needs"] == ["Same outline"])
check("the plan says where each metric comes from and what fails it",
      by["Outline"]["origin"] == "library" and by["Outline"]["limit"] == "min 0.9"
      and by["Structure"]["limit"].startswith("worse than the typical recipe") and by["Real photo (judges)"]["limit"] == "yes on every question"
      and by["Real photo (judges)"]["questions"] == ["Does image 2 look like a real photograph?"])

print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
sys.exit(1 if FAILED else 0)
