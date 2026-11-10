"""Does a video stay sharp? Sharpness of its last quarter relative to its first frame (1.0 = as sharp)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_sharpness_hold',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'info',
    'needs': ['video'],
    'unit': '× first frame',
    'direction': 'higher',
    'description': 'Does a video stay sharp? Sharpness of its last quarter relative to its first frame (1.0 = as sharp).',
}


def compute(pair, opt):
    """Laplacian variance per analysis frame. `value` is the median of the last quarter of the clip over
    the first frame; `lowest` is the softest frame anywhere. Fast motion lowers it honestly (motion
    blur), so read it next to `video_motion`."""
    v = video(pair)
    s = np.array([cv2.Laplacian(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var() for f in v["frames"]])
    if not len(s) or s[0] < 1e-9:
        return {"value": float("nan")}
    tail = s[-max(1, len(s) // 4):]
    return {"value": float(np.median(tail) / s[0]), "lowest": float(s.min() / s[0])}
