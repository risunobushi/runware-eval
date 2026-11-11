"""Words of reasoning the model left in its answer (`<think>...</think>` blocks), 0 = none. The other text checks read the answer without them; a pipeline that uses the answer as delivered gets them. Gate with `max: 0`."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'text_reasoning_leak',
    'trust': 'deterministic',
    'family': 'text',
    'kind': 'info',
    'needs': ['text_output'],
    'unit': 'words',
    'direction': 'lower',
    'description': 'Words of reasoning the model left in its answer (`<think>...</think>` blocks), 0 = none. The other text checks read the answer without them; a pipeline that uses the answer as delivered gets them. Gate with `max: 0`.',
}


def compute(p, opt):
    return {"value": float(len(words(reasoning(text(p)))))}
