# Metric catalogue (generated)

Generated from the metric files by `runware-eval metrics markdown`. Do not edit by hand: change the
metric's file and regenerate. This is the curated library; a bench can add its own in `metrics/`.

| id | kind | family | trust | needs | unit / direction | source | fingerprint |
|---|---|---|---|---|---|---|---|
| `deltaE2000_region` | preserve | colorimetric | deterministic | reference, region | ΔE2000 lower | library | `6365b592` |
| `seam_jump` | preserve | compositing | deterministic | reference, region | L* step lower | library | `fcaf1ee9` |
| `detail_similarity` | preserve | detail | deterministic | reference, region | NCC higher | library | `6f404af3` |
| `bbox_aspect` | preserve | geometric | deterministic | reference, region | ratio error lower | library | `797a2b6a` |
| `keypoint_match` | info | geometric | deterministic | reference, region | share matched higher | library | `3c59e488` |
| `mask_iou` | preserve | geometric | deterministic | reference, region | IoU higher | library | `d75569e8` |
| `phase_correlation` | preserve | geometric | deterministic | reference, region | px lower | library | `14f42359` |
| `size_aspect` | preserve | geometric | deterministic | reference | aspect ratio error lower | library | `8213e06e` |
| `mesh_faces` | info | mesh | deterministic | mesh | faces  | library | `6ff23914` |
| `mesh_file_mb` | info | mesh | deterministic | mesh | MB  | library | `8db6eef6` |
| `mesh_parts` | info | mesh | deterministic | mesh | count  | library | `c1edac4d` |
| `mesh_texture_px` | info | mesh | deterministic | mesh | px  | library | `beb5074c` |
| `mesh_watertight` | info | mesh | deterministic | mesh | 1 / 0  | library | `bad14b2b` |
| `sharpness_laplacian` | info | signal | deterministic | reference, region | × input higher | library | `a5bc32ac` |
| `ssim_region` | preserve | structural | deterministic | reference, region | SSIM higher | library | `7e925062` |
| `video_color_drift` | preserve | video | deterministic | video | ΔE2000 lower | library | `0d466561` |
| `video_duration` | info | video | deterministic | video | s  | library | `2a1e88cd` |
| `video_flicker` | info | video | deterministic | video | L* lower | library | `71ce71a4` |
| `video_frozen_frames` | info | video | deterministic | video | share of clip lower | library | `cb6e6f34` |
| `video_letterbox` | info | video | deterministic | video | share of frame lower | library | `3df76304` |
| `video_motion` | change | video | deterministic | video | % of diagonal / s higher | library | `25a07c68` |
| `video_scene_hold` | preserve | video | deterministic | video | histogram distance lower | library | `8f84df94` |
| `video_sharpness_hold` | info | video | deterministic | video | × first frame higher | library | `232b6671` |
| `video_texture_stability` | info | video | deterministic | video | L* residual lower | library | `f3d68cbf` |

- **`bbox_aspect`**: Proportions: relative difference of the region's bounding-box width/height ratios.
- **`deltaE2000_region`**: Colour change inside a region (CIEDE2000; options: ignore_lightness, l_range, erode_pct). Reports mean and p95.
- **`detail_similarity`**: Fine detail (lettering, stitching) kept? Best correlation of high-pass luminance over small offsets; survives lighting changes.
- **`keypoint_match`**: Share of the input's SIFT keypoints matched in the output at 512 px. Tracks light changes as much as product changes: info only.
- **`mask_iou`**: Does the output's outline overlap the input's? Intersection over union of the region masks.
- **`mesh_faces`**: Triangles in all geometries of a 3D output.
- **`mesh_file_mb`**: File size of a 3D output.
- **`mesh_parts`**: Connected components of a 3D output (thousands = fragmented).
- **`mesh_texture_px`**: Largest base-colour texture of a 3D output (0 = untextured).
- **`mesh_watertight`**: Is the 3D output a closed surface?
- **`phase_correlation`**: How far did the product move? Phase correlation between input and output product masks.
- **`seam_jump`**: Visible compositing: brightness step across a region's border, minus the step already in the input.
- **`sharpness_laplacian`**: Laplacian variance inside a region, relative to the input (1.0 = as sharp).
- **`size_aspect`**: Did the output keep the input's proportions? Relative error of width/height; also reports the native size.
- **`ssim_region`**: Structural similarity of luminance inside a region (option on: luminance_normalised).
- **`video_color_drift`**: Colour drift over a video: how far the average colour moves from the first frame (CIEDE2000; option ignore_lightness).
- **`video_duration`**: Length of a video output in seconds; also reports its frame rate and size.
- **`video_flicker`**: Brightness flicker in a video: frame-to-frame jumps in lightness that a smooth change would not have.
- **`video_frozen_frames`**: Share of a video in which the picture does not change at all (0 = always changing, 1 = a still image).
- **`video_letterbox`**: Black bars in a video: share of the frame taken by bars that stay black for the whole clip (0 = none).
- **`video_motion`**: How much moves in a video: mean optical flow, in percent of the frame diagonal per second. A still clip scores about 0.
- **`video_scene_hold`**: Does a video stay in one scene? Largest change in the picture's colour make-up within half a second (0 = same scene, 1 = nothing in common).
- **`video_sharpness_hold`**: Does a video stay sharp? Sharpness of its last quarter relative to its first frame (1.0 = as sharp).
- **`video_texture_stability`**: Do surfaces hold still as they move? What is left when each frame is moved onto the next along the measured motion (lower = steadier).
