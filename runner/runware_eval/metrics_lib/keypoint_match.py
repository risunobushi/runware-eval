"""Share of the input's SIFT keypoints matched in the output at 512 px. Tracks light changes as much as product changes: info only."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'keypoint_match',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'info',
    'needs': ['reference', 'region'],
    'unit': 'share matched',
    'direction': 'higher',
    'tolerance': 0.02,  # smallest difference that counts (margin of a limit set from results)
    'description': "Share of the input's SIFT keypoints matched in the output at 512 px. Tracks light changes as much as product changes: info only.",
}


def compute(p, opt):
    """Share of the original's SIFT keypoints (inside the product) that find a geometrically consistent
    match in the output, at a coarse scale. Caution: tested on relighting, it tracks how much the light
    changed more than whether the product changed, so it is not a reliable identity gate there."""
    spec = opt.get("region", "product")
    sc = opt.get("side_px", 512) / max(p.W, p.H)   # coarse scale: generated images redraw micro-texture
    g = lambda rgb: cv2.resize(cv2.cvtColor((rgb * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY), None,
                               fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
    m = lambda r: cv2.resize((r * 255).astype(np.uint8), None, fx=sc, fy=sc, interpolation=cv2.INTER_NEAREST)
    sift = cv2.SIFT_create(nfeatures=opt.get("max_points", 2000))
    ka, da = sift.detectAndCompute(g(p.rgb_in), m(p.region(spec)))
    kb, db = sift.detectAndCompute(g(p.rgb_out), m(p.region(spec, "out")))
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return {"value": 0.0, "points": len(ka or [])}
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, db, k=2)
    good = [m for m, n in (x for x in pairs if len(x) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 8:
        return {"value": len(good) / len(ka), "points": len(ka), "inliers": len(good)}
    src = np.float32([ka[m.queryIdx].pt for m in good])
    dst = np.float32([kb[m.trainIdx].pt for m in good])
    _, inl = cv2.findHomography(src, dst, cv2.RANSAC, opt.get("tolerance_px", 4.0))
    n = int(inl.sum()) if inl is not None else 0
    return {"value": n / len(ka), "points": len(ka), "inliers": n}
