"""Tokens the model wrote for this answer, as Runware reported them (thinking tokens are reported next to it). Only textInference reports it."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_output_tokens',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output'],
    'unit': 'tokens',
    'direction': 'lower',
    'description': 'Tokens the model wrote for this answer, as Runware reported them (thinking tokens are reported next to it). Only textInference reports it.',
}


def compute(p, opt):
    text(p)
    out = {"value": float(text_meta(p, "completionTokens"))}
    try:
        out["thinking"] = float(text_meta(p, "thinkingTokens"))
    except KeyError:
        pass
    return out
