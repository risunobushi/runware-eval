"""Share of the required terms that appear in the text (case-insensitive). Terms come from `terms:` on the check, or per input from the input's own `terms:`."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_terms',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output'],
    'unit': 'share found',
    'direction': 'higher',
    'description': "Share of the required terms that appear in the text (case-insensitive). Terms come from `terms:` on the check, or per input from the input's own `terms:`.",
}


def compute(p, opt):
    terms = opt.get("terms") or p.input.get("terms")
    if not terms:
        raise KeyError("no `terms` on the check or on this input")
    t = " ".join(text_part(p, opt).lower().split())
    missing = [x for x in terms if " ".join(str(x).lower().split()) not in t]
    return {"value": 1 - len(missing) / len(terms), "missing": ", ".join(map(str, missing))}
