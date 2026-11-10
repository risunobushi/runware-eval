"""Does a video stay in one scene? Largest change in the picture's colour make-up within half a second (0 = same scene, 1 = nothing in common)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_scene_hold',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'preserve',
    'needs': ['video'],
    'unit': 'histogram distance',
    'direction': 'lower',
    'description': "Does a video stay in one scene? Largest change in the picture's colour make-up within half a second (0 = same scene, 1 = nothing in common).",
}


def compute(pair, opt):
    """Each analysis frame is reduced to a colour histogram (CIELAB, 8 bins per axis), which does not
    care where things are, so motion inside a scene changes it little. A cut, or a set that is swapped
    for another, changes it a lot. `value` is the largest Bhattacharyya distance between frames half a
    second apart (`gap_s`, so quick fades count as well as hard cuts); `cut` is the largest distance
    between consecutive frames; `at_s` is when it happens; `from_start` compares the last frame with
    the first."""
    v = video(pair)
    fps = v["analysis_fps"]
    gap = max(1, int(round(float(opt.get("gap_s", 0.5)) * fps)))
    hists = []
    for f in v["frames"]:
        h = cv2.calcHist([cv2.cvtColor(f, cv2.COLOR_RGB2LAB)], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
        hists.append(cv2.normalize(h, None, 1.0, 0.0, cv2.NORM_L1).astype(np.float32))
    if len(hists) < 2:
        return {"value": float("nan")}
    dist = lambda a, b: float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))
    gap = min(gap, len(hists) - 1)
    wide = [dist(hists[i], hists[i + gap]) for i in range(len(hists) - gap)]
    step = [dist(a, b) for a, b in zip(hists, hists[1:])]
    return {"value": max(wide), "cut": max(step), "at_s": float((int(np.argmax(wide)) + gap) / fps),
            "from_start": dist(hists[0], hists[-1])}
