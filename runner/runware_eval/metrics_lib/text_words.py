"""Length of the text in words. Gate it from both sides (`min`, `max`) when the brief sets a length."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_words',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output'],
    'unit': 'words',
    'direction': '',
    'description': 'Length of the text in words. Gate it from both sides (`min`, `max`) when the brief sets a length.',
}


def compute(p, opt):
    t = text_part(p, opt)
    return {"value": float(len(words(t))), "chars": len(t)}
