"""Was the answer cut off by the token limit (`finishReason: length`)? Gate with `max: 0`. Only textInference reports it."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_truncated',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output'],
    'unit': '1 / 0',
    'direction': 'lower',
    'description': 'Was the answer cut off by the token limit (`finishReason: length`)? Gate with `max: 0`. Only textInference reports it.',
}


def compute(p, opt):
    text(p)
    reason = text_meta(p, "finishReason")
    return {"value": 1.0 if reason == "length" else 0.0, "finishReason": str(reason)}
