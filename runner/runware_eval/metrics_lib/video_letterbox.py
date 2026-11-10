"""Black bars in a video: share of the frame taken by bars that stay black for the whole clip (0 = none)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_letterbox',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'info',
    'needs': ['video'],
    'unit': 'share of frame',
    'direction': 'lower',
    'description': 'Black bars in a video: share of the frame taken by bars that stay black for the whole clip (0 = none).',
}


def compute(pair, opt):
    """Models with fixed output shapes pad an input of another shape. The runner leaves the bars out
    before every other check, so this is the one place they count. Gate with `max: 0` when the clip
    must be delivered without bars; `picture` is the size of what is left."""
    v = video(pair)
    return {"value": float(v["bars_share"]), "picture": f"{v['content_width']}x{v['content_height']}",
            "bars_top_bottom_left_right": v["bars"]}
