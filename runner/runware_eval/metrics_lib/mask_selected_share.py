"""How much of the frame the cut-out keeps or the mask selects (0 = nothing, 1 = everything). Needs no reference outline: 0 on a picture that has the subject, or 1 on any picture, is a failure whatever the reference says."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mask_selected_share',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'info',
    'needs': [],
    'unit': 'share of the frame',
    'direction': '',
    'description': 'How much of the frame the cut-out keeps or the mask selects (0 = nothing, 1 = everything). Needs no reference outline: 0 on a picture that has the subject, or 1 on any picture, is a failure whatever the reference says.',
}


def compute(p, opt):
    return {"value": float(own_outline(p).mean())}
