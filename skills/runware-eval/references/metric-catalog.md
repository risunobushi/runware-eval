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
| `mask_boundary_px` | preserve | geometric | deterministic | reference, region | px lower | library | `c177f08d` |
| `mask_box_fill` | info | geometric | deterministic | — | share of its box  | library | `20b935ff` |
| `mask_extra` | preserve | geometric | deterministic | reference, region | share of the reference lower | library | `28e458af` |
| `mask_inside` | preserve | geometric | deterministic | reference, region | share of the mask higher | library | `c1a690dd` |
| `mask_iou` | preserve | geometric | deterministic | reference, region | IoU higher | library | `d75569e8` |
| `mask_missing` | preserve | geometric | deterministic | reference, region | share of the reference lower | library | `783de562` |
| `mask_pieces` | info | geometric | deterministic | — | pieces lower | library | `0fa4c6ac` |
| `mask_selected_share` | info | geometric | deterministic | — | share of the frame  | library | `7e7bbecd` |
| `phase_correlation` | preserve | geometric | deterministic | reference, region | px lower | library | `14f42359` |
| `size_aspect` | preserve | geometric | deterministic | reference | aspect ratio error lower | library | `8213e06e` |
| `size_kept` | preserve | geometric | deterministic | reference | × input higher | library | `1613224d` |
| `upscale_factor` | info | geometric | deterministic | reference | × input higher | library | `516371df` |
| `mesh_faces` | info | mesh | deterministic | mesh | faces  | library | `6ff23914` |
| `mesh_file_mb` | info | mesh | deterministic | mesh | MB  | library | `8db6eef6` |
| `mesh_parts` | info | mesh | deterministic | mesh | count  | library | `c1edac4d` |
| `mesh_texture_px` | info | mesh | deterministic | mesh | px  | library | `beb5074c` |
| `mesh_watertight` | info | mesh | deterministic | mesh | 1 / 0  | library | `bad14b2b` |
| `alpha_edge_softness` | info | signal | deterministic | — | px  | library | `43d3ce7c` |
| `alpha_opacity` | preserve | signal | deterministic | reference, region | mean alpha higher | library | `cc791229` |
| `sharpness_laplacian` | info | signal | deterministic | reference, region | × input higher | library | `a5bc32ac` |
| `upscale_detail_gain` | info | signal | deterministic | reference | × plain resize higher | library | `44ba8c21` |
| `upscale_truth_psnr` | info | signal | deterministic | reference | dB higher | library | `cd478750` |
| `ssim_region` | preserve | structural | deterministic | reference, region | SSIM higher | library | `7e925062` |
| `upscale_truth_ssim` | info | structural | deterministic | reference | SSIM higher | library | `d77a840f` |
| `text_banned` | info | text | deterministic | text_output | terms found lower | library | `5f404c98` |
| `text_json` | info | text | deterministic | text_output | 1 / 0 higher | library | `04ee7650` |
| `text_output_tokens` | info | text | deterministic | text_output | tokens lower | library | `9abb65cd` |
| `text_reasoning_leak` | info | text | deterministic | text_output | words lower | library | `b3060630` |
| `text_reference_f1` | info | text | deterministic | text_output, reference | F1 higher | library | `a54f8ded` |
| `text_regex` | info | text | deterministic | text_output | 1 / 0 higher | library | `f26ae16f` |
| `text_sentences` | info | text | deterministic | text_output | sentences  | library | `bec1c69c` |
| `text_terms` | info | text | deterministic | text_output | share found higher | library | `71903cb0` |
| `text_truncated` | info | text | deterministic | text_output | 1 / 0 lower | library | `b42cbe84` |
| `text_words` | info | text | deterministic | text_output | words  | library | `545916af` |
| `svg_colours` | info | vector | deterministic | — | colours  | library | `659aac76` |
| `svg_file_kb` | info | vector | deterministic | — | KB lower | library | `f4ea1f3d` |
| `svg_images` | info | vector | deterministic | — | bitmaps lower | library | `5e940a82` |
| `svg_nodes` | info | vector | deterministic | — | nodes lower | library | `ffa822a3` |
| `svg_shapes` | info | vector | deterministic | — | shapes lower | library | `f240d097` |
| `video_color_drift` | preserve | video | deterministic | video | ΔE2000 lower | library | `45d46b77` |
| `video_duration` | info | video | deterministic | video | s  | library | `2a1e88cd` |
| `video_flicker` | info | video | deterministic | video | L* lower | library | `a5dbc74f` |
| `video_frozen_frames` | info | video | deterministic | video | share of clip lower | library | `cb6e6f34` |
| `video_letterbox` | info | video | deterministic | video | share of frame lower | library | `3df76304` |
| `video_motion` | change | video | deterministic | video | % of diagonal / s higher | library | `8bcfb71f` |
| `video_outline_hold` | preserve | video | deterministic | video, reference, region | IoU higher | library | `18bdef48` |
| `video_product_area` | info | video | deterministic | video, reference, region | × input area  | library | `fa17950f` |
| `video_product_drift` | preserve | video | deterministic | video, reference, region | histogram distance lower | library | `db0ee2b2` |
| `video_scene_hold` | preserve | video | deterministic | video | histogram distance lower | library | `bb3426bb` |
| `video_sharpness_hold` | info | video | deterministic | video | × first frame higher | library | `a39b0390` |
| `video_texture_stability` | info | video | deterministic | video | L* residual lower | library | `c51746af` |

- **`alpha_edge_softness`**: Width of the cut-out's semi-transparent edge, in pixels at the input's size: about 0 is a hard, jagged edge, 1 to 3 a clean anti-aliased one, more a soft matte (hair, fur, glass) or a halo. No better direction on its own.
- **`alpha_opacity`**: How solid the cut-out is inside the reference region, away from its edge: mean alpha, 1 = fully opaque. Below about 0.99 the subject itself was left partly see-through (the new background will show through it). Also reports the share of pixels under 90% opacity.
- **`bbox_aspect`**: Proportions: relative difference of the region's bounding-box width/height ratios.
- **`deltaE2000_region`**: Colour change inside a region (CIEDE2000; options: ignore_lightness, l_range, erode_pct). Reports mean and p95.
- **`detail_similarity`**: Fine detail (lettering, stitching) kept? Best correlation of high-pass luminance over small offsets; survives lighting changes.
- **`keypoint_match`**: Share of the input's SIFT keypoints matched in the output at 512 px. Tracks light changes as much as product changes: info only.
- **`mask_boundary_px`**: How far the output's outline is from the reference outline: mean distance in pixels at the input's size, both ways (also p95). Catches a ragged or shifted edge that overlap (mask_iou) hides on a large shape.
- **`mask_box_fill`**: How much of its own bounding box the cut-out or mask fills (per piece, weighted by area): 1.0 is a plain rectangle, a traced subject is well below. Tells a detector's box from a real outline without any reference.
- **`mask_extra`**: How much the output selects or keeps outside the reference region, as a share of the reference's area (0 = nothing extra). For a cut-out: background left in.
- **`mask_inside`**: How much of what the mask selects lies inside the reference region (1 = all of it). For a mask of a part (a face, a hand) checked against the outline of the whole (the person): the part must sit inside it.
- **`mask_iou`**: Does the output's outline overlap the input's? Intersection over union of the region masks.
- **`mask_missing`**: How much of the reference region the output leaves out (0 = nothing missing). For a cut-out: parts of the subject cut away.
- **`mask_pieces`**: Separate pieces in the cut-out or mask, counting only pieces above 0.05% of the frame (or 5% of the selection, when that is smaller). One product is one piece: more means stray islands of backdrop, or a subject cut apart. Also reports the share of the selection in the largest piece and the holes inside it.
- **`mask_selected_share`**: How much of the frame the cut-out keeps or the mask selects (0 = nothing, 1 = everything). Needs no reference outline: 0 on a picture that has the subject, or 1 on any picture, is a failure whatever the reference says.
- **`mesh_faces`**: Triangles in all geometries of a 3D output.
- **`mesh_file_mb`**: File size of a 3D output.
- **`mesh_parts`**: Connected components of a 3D output (thousands = fragmented).
- **`mesh_texture_px`**: Largest base-colour texture of a 3D output (0 = untextured).
- **`mesh_watertight`**: Is the 3D output a closed surface?
- **`phase_correlation`**: How far did the product move? Phase correlation between input and output product masks.
- **`seam_jump`**: Visible compositing: brightness step across a region's border, minus the step already in the input.
- **`sharpness_laplacian`**: Laplacian variance inside a region, relative to the input (1.0 = as sharp).
- **`size_aspect`**: Did the output keep the input's proportions? Relative error of width/height; also reports the native size.
- **`size_kept`**: Delivered width and height over the input's (1.0 = the same size). For tools that should hand back the picture at its own size (background removal, masking, edits): below 1 the result came back smaller and resolution was lost. Also reports the delivered size.
- **`ssim_region`**: Structural similarity of luminance inside a region (option on: luminance_normalised).
- **`svg_colours`**: Distinct fill and stroke colours in the SVG. A brand mark should have a handful; hundreds means gradients were traced into flat steps.
- **`svg_file_kb`**: Size of the SVG file.
- **`svg_images`**: Bitmaps embedded in the SVG. Anything above 0 is a picture in an SVG wrapper, not a vector drawing: gate with `max: 0`.
- **`svg_nodes`**: Anchor points over all shapes of the SVG: how heavy the drawing is to edit and render.
- **`svg_shapes`**: Drawing elements in the SVG (paths, rectangles, circles ...). Fewer is easier to edit; thousands means a traced photo.
- **`text_banned`**: How many of the banned terms appear in the text (case-insensitive). Terms come from `banned:` on the check, or per input from the input's own `banned:`. Gate with `max: 0`.
- **`text_json`**: Is the text valid JSON (a code fence around it is allowed)? With `keys: [...]` on the check, the object must also have every one of those keys.
- **`text_output_tokens`**: Tokens the model wrote for this answer, as Runware reported them (thinking tokens are reported next to it). Only textInference reports it.
- **`text_reasoning_leak`**: Words of reasoning the model left in its answer (`<think>...</think>` blocks), 0 = none. The other text checks read the answer without them; a pipeline that uses the answer as delivered gets them. Gate with `max: 0`.
- **`text_reference_f1`**: Word overlap between the text and the input's `reference:` text (F1 of shared words, 0 to 1). It rewards the same words, not the same meaning: a good paraphrase scores low, so pair it with a judge.
- **`text_regex`**: Does the text match the regular expression in `pattern:` (searched anywhere, case-insensitive unless `case: true`)? For a fixed format: a SKU, a date, one sentence.
- **`text_sentences`**: Sentences in the text (or in one JSON field with `field:`). For "one sentence" or "at most three": gate with `max`. Counts runs of text that end in . ! or ?; a decimal point or an abbreviation with a full stop inside a word does not count.
- **`text_terms`**: Share of the required terms that appear in the text (case-insensitive). Terms come from `terms:` on the check, or per input from the input's own `terms:`.
- **`text_truncated`**: Was the answer cut off by the token limit (`finishReason: length`)? Gate with `max: 0`. Only textInference reports it.
- **`text_words`**: Length of the text in words. Gate it from both sides (`min`, `max`) when the brief sets a length.
- **`upscale_detail_gain`**: Fine detail at the output's own size, relative to the input enlarged by plain resampling (1.0 = no more detail than a resize). More is not always better: detail the input never had is invented, so read it next to a fidelity check.
- **`upscale_factor`**: How much larger the output is than the input: output width / input width (2.0 = twice as wide). Also reports the delivered size.
- **`upscale_truth_psnr`**: Pixel error against the full-size original the input was shrunk from (the input's `original:` file), as PSNR in dB: higher is closer. Strict about every pixel, so a sharper but slightly different texture scores below a blurry one: read it next to upscale_truth_ssim and upscale_detail_gain.
- **`upscale_truth_ssim`**: How close the upscaled picture is to the full-size original the input was shrunk from (the input's `original:` file), at the original's size: SSIM of luminance, 1 = identical. Also reports what a plain resize of the input scores (`plain_resize`) and the difference: below 0, the upscaler did worse than no upscaler. The only upscale check that tells recovered detail from invented detail.
- **`video_color_drift`**: Colour drift over a video: how far the average colour moves from the first frame (CIEDE2000; option ignore_lightness).
- **`video_duration`**: Length of a video output in seconds; also reports its frame rate and size.
- **`video_flicker`**: Brightness flicker in a video: frame-to-frame jumps in lightness that a smooth change would not have.
- **`video_frozen_frames`**: Share of a video in which the picture does not change at all (0 = always changing, 1 = a still image).
- **`video_letterbox`**: Black bars in a video: share of the frame taken by bars that stay black for the whole clip (0 = none).
- **`video_motion`**: How much moves in a video: mean optical flow, in percent of the frame diagonal per second. A still clip scores about 0.
- **`video_outline_hold`**: Does the product keep its outline through a video? Lowest overlap (IoU) between its outline in the sample frames and in the input.
- **`video_product_area`**: Does the product stay in the picture? Its smallest area in the sample frames of a video, relative to its area in the input (1.0 = same size).
- **`video_product_drift`**: Is it still the same product later in the video? Largest change in the colour make-up of the product, frame outline against the input's (0 = same colours, 1 = nothing in common).
- **`video_scene_hold`**: Does a video stay in one scene? Largest change in the picture's colour make-up within half a second (0 = same scene, 1 = nothing in common).
- **`video_sharpness_hold`**: Does a video stay sharp? Sharpness of its last quarter relative to its first frame (1.0 = as sharp).
- **`video_texture_stability`**: Do surfaces hold still as they move? What is left when each frame is moved onto the next along the measured motion (lower = steadier).
