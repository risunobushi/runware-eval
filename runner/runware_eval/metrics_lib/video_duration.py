"""Length of a video output in seconds; also reports its frame rate and size."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_duration',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'info',
    'needs': ['video'],
    'unit': 's',
    'direction': '',
    'description': 'Length of a video output in seconds; also reports its frame rate and size.',
}


def compute(pair, opt):
    v = video(pair)
    return {"value": float(v["duration"]), "fps": v["native_fps"], "size": f"{v['width']}x{v['height']}"}
