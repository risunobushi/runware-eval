"""Render adapter: turn a 3D output (GLB) into images, so the image checks apply unchanged.

The mesh is rendered unlit (texture colours only) with an orthographic camera. Because every model
orients its mesh differently, the adapter searches yaw x elevation x up-axis for the view whose
silhouette best matches the input's product mask, then renders that view at full size and places it
on the input's canvas (scaled to the product's height, centred on it). Mesh-level facts (faces,
watertight, parts, texture) are read from the file itself.

Rendering uses PyVista/VTK, which ships its own OpenGL and works offscreen on Windows, macOS and Linux.
"""
import os

import numpy as np
import trimesh
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

MESH_EXT = (".glb", ".gltf")


def is_mesh(path):
    return os.path.splitext(path)[1].lower() in MESH_EXT


def _geometries(path):
    sc = trimesh.load(path, force="scene")
    out = []
    for name, g in sc.geometry.items():
        if not isinstance(g, trimesh.Trimesh) or not len(g.faces):
            continue
        # place each geometry where the scene graph puts it
        nodes = sc.graph.geometry_nodes.get(name, [])
        T = sc.graph.get(nodes[0])[0] if nodes else np.eye(4)
        g = g.copy()
        g.apply_transform(T)
        out.append(g)
    return out


def mesh_facts(path):
    geos = _geometries(path)
    faces = sum(len(g.faces) for g in geos)
    parts, watertight, tex = 0, True, 0
    for g in geos:
        adj = g.face_adjacency
        n = len(g.faces)
        k, _ = connected_components(coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(n, n)),
                                    directed=False)
        parts += k
        watertight &= bool(g.is_watertight)
        img = getattr(getattr(g.visual, "material", None), "baseColorTexture", None)
        if img is not None:
            tex = max(tex, max(img.size))
    return {"faces": faces, "vertices": sum(len(g.vertices) for g in geos), "parts": int(parts),
            "watertight": watertight, "texture_px": tex, "file_mb": os.path.getsize(path) / 1e6}


def _pv_meshes(geos):
    import pyvista as pv
    out = []
    for g in geos:
        m = pv.PolyData(np.asarray(g.vertices), np.hstack([np.full((len(g.faces), 1), 3), g.faces]).ravel())
        kw = {"lighting": False}
        vis = g.visual
        img = getattr(getattr(vis, "material", None), "baseColorTexture", None)
        uv = getattr(vis, "uv", None)
        if img is not None and uv is not None and len(uv) == len(g.vertices):
            m.active_texture_coordinates = np.asarray(uv, dtype=np.float32)
            kw["texture"] = pv.Texture(np.asarray(img.convert("RGB")))
        elif hasattr(vis, "vertex_colors") and len(getattr(vis, "vertex_colors", [])) == len(g.vertices):
            m.point_data["rgb"] = np.asarray(vis.vertex_colors)[:, :3]
            kw.update(scalars="rgb", rgb=True)
        else:
            f = getattr(getattr(vis, "material", None), "baseColorFactor", None)
            kw["color"] = (np.asarray(f[:3]) / (255 if np.max(f[:3]) > 1 else 1)) if f is not None else "lightgray"
        out.append((m, kw))
    return out


def render(meshes, center, radius, yaw, elev, up, size):
    """Orthographic, unlit render from a direction given by yaw/elevation around the `up` axis."""
    import pyvista as pv
    up = np.asarray(up, float)
    fwd0 = np.array([0, 0, 1.0]) if abs(up[2]) < 0.9 else np.array([0, -1.0, 0])
    side = np.cross(up, fwd0)
    y, e = np.radians(yaw), np.radians(elev)
    d = (np.cos(e) * (np.cos(y) * fwd0 + np.sin(y) * side) + np.sin(e) * up)
    pl = pv.Plotter(off_screen=True, window_size=(size, size))
    pl.set_background("white")
    for m, kw in meshes:
        pl.add_mesh(m, **kw)
    pl.enable_parallel_projection()
    pl.camera.position = tuple(center + d * radius * 4)
    pl.camera.focal_point = tuple(center)
    pl.camera.up = tuple(up)
    pl.camera.parallel_scale = radius * 1.02  # radius is half the bounding-box diagonal: the whole model fits
    pl.camera.clipping_range = (radius * 0.5, radius * 8)
    img = pl.screenshot(return_img=True, transparent_background=True)
    pl.close()
    return img


def _bbox(mask):
    ys, xs = np.nonzero(mask)
    return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(xs) else None


def _place(rgba, target_box, W, H):
    """Scale the render's subject to the target box height and centre it there, on a W x H canvas."""
    a = rgba[..., 3] > 0
    bb = _bbox(a)
    if bb is None:
        return np.zeros((H, W, 4), np.uint8)
    x0, y0, x1, y1 = bb
    tx0, ty0, tx1, ty1 = target_box
    s = (ty1 - ty0) / (y1 - y0)
    crop = Image.fromarray(rgba[y0:y1, x0:x1])
    nw, nh = max(1, round((x1 - x0) * s)), max(1, round((y1 - y0) * s))
    crop = crop.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx = (tx0 + tx1) / 2 - nw / 2
    canvas.paste(crop, (int(round(cx)), int(ty0)), crop)
    return np.asarray(canvas)


def _iou(a, b):
    return (a & b).sum() / max(1, (a | b).sum())


def front_view(path, target_mask, bg_rgb, out_png, out_mask, search_px=192, final_px=1024, log=None):
    """Find the view matching the input silhouette, render it, place it on the input canvas.

    Writes the composite (render over the input's background colour) and its silhouette mask.
    Returns the chosen view and the silhouette IoU found during the search."""
    H, W = target_mask.shape
    tb = _bbox(target_mask)
    geos = _geometries(path)
    allv = np.vstack([g.vertices for g in geos])
    center = (allv.min(0) + allv.max(0)) / 2
    radius = float(np.linalg.norm(allv.max(0) - allv.min(0))) / 2
    meshes = _pv_meshes(geos)
    small = np.asarray(Image.fromarray(target_mask.astype(np.uint8) * 255).resize(
        (max(1, W * search_px // max(W, H)), max(1, H * search_px // max(W, H))), Image.NEAREST)) > 127
    stb = _bbox(small)
    best = (-1, None)
    for up in ((0, 1, 0), (0, 0, 1)):
        for elev in (-25, 0, 25):
            for yaw in range(0, 360, 15):
                img = render(meshes, center, radius, yaw, elev, up, search_px)
                placed = _place(img, stb, small.shape[1], small.shape[0])[..., 3] > 0
                score = _iou(placed, small)
                if score > best[0]:
                    best = (score, (yaw, elev, up))
    yaw, elev, up = best[1]
    img = render(meshes, center, radius, yaw, elev, up, final_px)
    placed = _place(img, tb, W, H)
    alpha = placed[..., 3:4].astype(np.float32) / 255
    comp = alpha * placed[..., :3] + (1 - alpha) * np.asarray(bg_rgb, np.float32)
    Image.fromarray(comp.astype(np.uint8)).save(out_png)
    Image.fromarray(((placed[..., 3] > 0) * 255).astype(np.uint8)).save(out_mask)
    return {"yaw": yaw, "elevation": elev, "up": list(up), "search_iou": float(best[0])}


def turntable(path, out_png, px=384, views=(0, 90, 180, 270)):
    """A strip of views around the chosen up axis, for the report."""
    geos = _geometries(path)
    allv = np.vstack([g.vertices for g in geos])
    center = (allv.min(0) + allv.max(0)) / 2
    radius = float(np.linalg.norm(allv.max(0) - allv.min(0))) / 2
    meshes = _pv_meshes(geos)
    strip = [render(meshes, center, radius, y, 10, (0, 1, 0), px) for y in views]
    out = np.concatenate([np.where(s[..., 3:4] > 0, s[..., :3], 255) for s in strip], axis=1).astype(np.uint8)
    Image.fromarray(out).save(out_png)
    return out_png
