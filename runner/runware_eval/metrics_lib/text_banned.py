"""How many of the banned terms appear in the text (case-insensitive). Terms come from `banned:` on the check, or per input from the input's own `banned:`. Gate with `max: 0`."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_banned',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output'],
    'unit': 'terms found',
    'direction': 'lower',
    'description': "How many of the banned terms appear in the text (case-insensitive). Terms come from `banned:` on the check, or per input from the input's own `banned:`. Gate with `max: 0`.",
}


def compute(p, opt):
    banned = opt.get("banned") or p.input.get("banned")
    if not banned:
        raise KeyError("no `banned` on the check or on this input")
    t = " ".join(text_part(p, opt).lower().split())
    found = [x for x in banned if " ".join(str(x).lower().split()) in t]
    return {"value": float(len(found)), "found": ", ".join(map(str, found))}
