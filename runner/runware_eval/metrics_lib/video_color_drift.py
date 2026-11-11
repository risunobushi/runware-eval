"""Colour drift over a video: how far the average colour moves from the first frame (CIEDE2000; option ignore_lightness)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_color_drift',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'preserve',
    'needs': ['video'],
    'unit': 'ΔE2000',
    'direction': 'lower',
    'tolerance': 1.0,  # smallest difference that counts (margin of a limit set from results)
    'description': 'Colour drift over a video: how far the average colour moves from the first frame (CIEDE2000; option ignore_lightness).',
}


def compute(pair, opt):
    """Each analysis frame is reduced to its average colour, which does not care where things are in the
    frame, so camera and subject motion do not count as drift. `value` is the largest distance from the
    first frame at any time; `end` is the distance at the last frame. With `ignore_lightness: true` only
    hue and chroma count (use it when the brief asks for a lighting change)."""
    v = video(pair)
    mean = np.array([rgb2lab(f.reshape(-1, 1, 3) / 255.0).reshape(-1, 3).mean(axis=0) for f in v["frames"]])
    ref = np.repeat(mean[:1], len(mean), axis=0)
    cur = mean.copy()
    if opt.get("ignore_lightness"):
        cur[:, 0] = ref[:, 0]
    de = deltaE_ciede2000(ref, cur)
    return {"value": float(de.max()), "end": float(de[-1]), "at_s": float(de.argmax() / v["analysis_fps"]),
            "series": series(de, v["analysis_fps"])}
