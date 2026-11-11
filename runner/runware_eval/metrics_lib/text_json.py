"""Is the text valid JSON (a code fence around it is allowed)? With `keys: [...]` on the check, the object must also have every one of those keys."""
import json
import re

from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_json',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output'],
    'unit': '1 / 0',
    'direction': 'higher',
    'description': 'Is the text valid JSON (a code fence around it is allowed)? With `keys: [...]` on the check, the object must also have every one of those keys.',
}


def compute(p, opt):
    t, fenced = unfence(answer(text(p)))
    if opt.get("strict"):  # what `json.loads` on the raw answer would see
        t, fenced = text(p).strip(), False
    try:
        data = json.loads(t)
    except ValueError:
        return {"value": 0.0, "note": "not valid JSON"}
    keys = opt.get("keys") or []
    missing = [k for k in keys if not (isinstance(data, dict) and k in data)]
    return {"value": 0.0 if missing else 1.0, "missing": ", ".join(missing), "fenced": fenced}
