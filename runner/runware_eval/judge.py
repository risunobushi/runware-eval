"""Vision-model judges on Runware: checklists, same-object checks and rubric scores.

Every question goes to a panel of models from different providers (bench.yaml `judges`), so no
single model's taste decides. Images are sent inline as JPEG data URIs, which keeps judging
independent of output URL expiry. Answers are cached in judges.jsonl next to the outputs.

Request shape (verified on Gemini, Claude and GPT): images in `inputs.images`, sampling options
under `settings`; only some providers accept `outputFormat: JSON`, so answers are also parsed
from plain text.
"""
import base64
import hashlib
import io
import json
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from . import api

DEFAULT_JUDGES = ["google-gemini-3-1-flash-lite", "anthropic-claude-haiku-4-5", "openai-gpt-5-4-nano"]
JSON_NATIVE = ("google-",)
EST_COST_PER_CALL = 0.002  # one combined call, measured: $0.0007-0.0038 depending on the judge

SAME_OBJECT = ("Is the product in image 2 the same physical product as in image 1: same design, shape, "
               "colours, materials, hardware and details? Ignore lighting, shadows and background.")


def data_uri(rgb, long_side=1024):
    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    s = long_side / max(img.size)
    if s < 1:
        img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def parse_json(text):
    """Accept bare JSON, fenced ```json blocks, or JSON embedded in prose."""
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None


class Panel:
    def __init__(self, judges, out_dir, log=print):
        self.judges = judges or DEFAULT_JUDGES
        self.path = os.path.join(out_dir, "judges.jsonl")
        self.cache = {}
        if os.path.exists(self.path):
            for line in open(self.path, encoding="utf8"):
                if line.strip():
                    r = json.loads(line)
                    self.cache[r["key"]] = r
        self.lock = threading.Lock()
        self.spent = 0.0
        self.log = log

    def _ask(self, judge, prompt, images, schema):
        key = hashlib.sha1(json.dumps([judge, prompt, [hashlib.sha1(i.encode()).hexdigest() for i in images]])
                           .encode()).hexdigest()
        if key in self.cache and self.cache[key]["status"] == "success":
            return self.cache[key]  # failed answers are asked again
        task = {"taskType": "textInference", "taskUUID": str(uuid.uuid4()), "model": judge, "includeCost": True,
                "messages": [{"role": "user", "content": prompt}], "inputs": {"images": images},
                "settings": {"temperature": 0, "maxTokens": 4000}}  # reasoning models spend tokens before answering
        if judge.startswith(JSON_NATIVE):
            task.update(outputFormat="JSON", jsonSchema=schema)
        for _ in range(2):  # one retry: replies are occasionally empty or cut off
            task["taskUUID"] = str(uuid.uuid4())
            res = api.run_task(task, max_wait=180)
            parsed = parse_json(res.get("text")) if res["status"] == "success" else None
            if parsed:
                break
        row = {"key": key, "judge": judge, "status": res["status"] if parsed else "error",
               "answer": parsed, "error": res.get("error") or (None if parsed else "unparseable reply"),
               "cost": res.get("cost") or 0.0, "raw": None if parsed else (res.get("text") or "")[:500]}
        with self.lock:
            self.spent += row["cost"]
            self.cache[key] = row
            with open(self.path, "a", encoding="utf8") as f:
                f.write(json.dumps(row) + "\n")
        return row

    def ask_all(self, prompt, images, schema):
        with ThreadPoolExecutor(max_workers=len(self.judges)) as pool:
            return list(pool.map(lambda j: self._ask(j, prompt, images, schema), self.judges))

    # ---- metric types ----

    def checklist(self, questions, images, intro):
        qs = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
        prompt = (f"{intro}\nAnswer each question strictly with yes or no.\n{qs}\n"
                  'Reply with JSON only: {"answers":[{"q":1,"answer":"yes"},...]}')
        schema = {"type": "object", "additionalProperties": False, "required": ["answers"], "properties": {
            "answers": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                        "required": ["q", "answer"], "properties": {"q": {"type": "integer"},
                        "answer": {"type": "string", "enum": ["yes", "no"]}}}}}}
        rows = self.ask_all(prompt, images, schema)
        per_judge, grid = {}, []
        for r in rows:
            if r["status"] != "success":
                continue
            ans = {a.get("q"): str(a.get("answer", "")).lower() == "yes" for a in r["answer"].get("answers", [])}
            vals = [ans.get(i) for i in range(1, len(questions) + 1)]
            if None in vals:
                continue
            per_judge[r["judge"]] = float(np.mean(vals))
            grid.append(vals)
        if not grid:
            return {"value": float("nan"), "note": "no judge answered"}
        grid = np.array(grid)
        agreement = float(np.mean([grid[:, i].all() or (~grid[:, i]).all() for i in range(grid.shape[1])]))
        per_q = {questions[i]: float(grid[:, i].mean()) for i in range(grid.shape[1])}
        return {"value": float(grid.mean()), "judges": per_judge, "agreement": agreement, "per_question": per_q,
                "answered": len(grid), "asked": len(rows)}

    def rubric(self, rubric, images, intro, scale=(1, 5)):
        lo, hi = scale
        prompt = (f"{intro}\nScore image 2 from {lo} (poor) to {hi} (excellent) on: {rubric}\n"
                  'Reply with JSON only: {"score": <integer>}')
        schema = {"type": "object", "additionalProperties": False, "required": ["score"],
                  "properties": {"score": {"type": "integer", "minimum": lo, "maximum": hi}}}
        rows = self.ask_all(prompt, images, schema)
        scores = {r["judge"]: float(r["answer"]["score"]) for r in rows
                  if r["status"] == "success" and isinstance(r["answer"], dict) and "score" in r["answer"]}
        if not scores:
            return {"value": float("nan"), "note": "no judge answered"}
        return {"value": float(np.mean(list(scores.values()))), "judges": scores,
                "spread": float(max(scores.values()) - min(scores.values()))}


def total_cost(out_dir):
    """Everything ever spent on judge calls for this run folder (including answers later retried)."""
    path = os.path.join(out_dir, "judges.jsonl")
    if not os.path.exists(path):
        return 0.0
    return sum(json.loads(l).get("cost") or 0 for l in open(path, encoding="utf8") if l.strip())


def run_combined(panel, prepared, opts):
    """All vlm_* metrics that share an image set, in ONE call per judge. Returns values per metric."""
    images, intro = prepared
    questions, spans, rubric = [], [], None
    for o in opts:
        qs = o.get("questions") or ([SAME_OBJECT] if o["id"] == "vlm_same_object" else [])
        spans.append((len(questions), len(questions) + len(qs)))
        questions += qs
        if o["id"] == "vlm_rubric":
            rubric = (o["rubric"], tuple(int(x) for x in str(o.get("scale", "1-5")).split("-")))
    lines = [f"{intro}", "Answer about image 2."]
    if questions:
        lines.append("Answer each question strictly with yes or no.")
        lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    if rubric:
        lines.append(f"Then score image 2 from {rubric[1][0]} (poor) to {rubric[1][1]} (excellent) on: {rubric[0]}")
    shape = []
    if questions:
        shape.append('"answers":[{"q":1,"answer":"yes"},...]')
    if rubric:
        shape.append('"score":<integer>')
    lines.append("Reply with JSON only: {" + ",".join(shape) + "}")
    props, req = {}, []
    if questions:
        props["answers"] = {"type": "array", "items": {"type": "object", "additionalProperties": False,
                            "required": ["q", "answer"], "properties": {"q": {"type": "integer"},
                            "answer": {"type": "string", "enum": ["yes", "no"]}}}}
        req.append("answers")
    if rubric:
        props["score"] = {"type": "integer", "minimum": rubric[1][0], "maximum": rubric[1][1]}
        req.append("score")
    schema = {"type": "object", "additionalProperties": False, "required": req, "properties": props}
    rows = [r for r in panel.ask_all("\n".join(lines), images, schema) if r["status"] == "success"]
    grid, scores = {}, {}
    for r in rows:
        a = r["answer"] if isinstance(r["answer"], dict) else {}
        ans = {x.get("q"): str(x.get("answer", "")).lower() == "yes" for x in a.get("answers", [])}
        if questions and all(i in ans for i in range(1, len(questions) + 1)):
            grid[r["judge"]] = [ans[i] for i in range(1, len(questions) + 1)]
        if rubric and isinstance(a.get("score"), (int, float)):
            scores[r["judge"]] = float(a["score"])
    out = []
    for o, (s0, s1) in zip(opts, spans):
        if o["id"] == "vlm_rubric":
            out.append({"value": float(np.mean(list(scores.values()))), "judges": scores,
                        "spread": float(max(scores.values()) - min(scores.values()))} if scores
                       else {"value": float("nan"), "note": "no judge answered"})
            continue
        sub = {j: v[s0:s1] for j, v in grid.items()}
        if not sub:
            out.append({"value": float("nan"), "note": "no judge answered"})
            continue
        g = np.array(list(sub.values()))
        out.append({"value": float(g.mean()), "judges": {j: float(np.mean(v)) for j, v in sub.items()},
                    "agreement": float(np.mean([g[:, i].all() or (~g[:, i]).all() for i in range(g.shape[1])])),
                    "per_question": {questions[s0 + i]: float(g[:, i].mean()) for i in range(g.shape[1])}})
    return out


def crop(rgb, region):
    ys, xs = np.nonzero(region)
    pad = max(8, int(0.04 * max(rgb.shape[:2])))
    y0, y1 = max(0, ys.min() - pad), min(rgb.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(rgb.shape[1], xs.max() + pad)
    return rgb[y0:y1, x0:x1]


INTRO = ("Image 1 is the original product photo. Image 2 is the same photo after an AI edit. "
         "Judge image 2, comparing with image 1 where a question needs it.")
INTRO_CROP = ("Image 1 is a close-up crop of the original product photo. Image 2 is the same crop after an "
              "AI edit. Judge image 2, comparing with image 1 where a question needs it.")


def prepare(p, opt, b=None):
    """Inline images and intro for one vlm_* metric on one input/output pair (a score.Pair).

    `refs: [<media name>, ...]` on the metric adds top-level media (e.g. a lighting reference) as
    images 3, 4, ... so questions like "as in the reference" can actually be checked.
    """
    region = opt.get("region")
    if region:
        r = p.region(region)
        images, intro = [data_uri(crop(p.rgb_in, r)), data_uri(crop(p.rgb_out, r))], INTRO_CROP
    else:
        images, intro = [data_uri(p.rgb_in), data_uri(p.rgb_out)], INTRO
    for i, name in enumerate(opt.get("refs") or [], start=3):
        entry = (b or {}).get(name)
        if not (isinstance(entry, dict) and "path" in entry):
            raise KeyError(f"refs: '{name}' is not a top-level media entry in bench.yaml")
        rgb = np.asarray(Image.open(os.path.join(b["_dir"], entry["path"])).convert("RGB")) / 255.0
        images.append(data_uri(rgb))
        intro += f" Image {i} is the reference '{name.replace('_', ' ')}': use it only where a question mentions it."
    return images, intro


def run_prepared(panel, prepared, opt):
    images, intro = prepared
    if opt["id"] == "vlm_checklist":
        return panel.checklist(opt["questions"], images, intro)
    if opt["id"] == "vlm_same_object":
        return panel.checklist([SAME_OBJECT], images, intro)
    if opt["id"] == "vlm_rubric":
        lo, hi = (int(x) for x in str(opt.get("scale", "1-5")).split("-"))
        return panel.rubric(opt["rubric"], images, intro, (lo, hi))
    raise KeyError(opt["id"])
