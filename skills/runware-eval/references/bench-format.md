# bench.yaml format

One file describes a bench completely. The runner reads it; an agent writes it. Adding a model
later means adding one recipe and re-running. Results are cached by a hash of
(input, recipe, seed), so a re-run only pays for new combinations.

## Fields

| Field | Meaning |
|---|---|
| `goal` | The user's goal in their own words. |
| `task` | Optional. One short sentence shown under the report's headline as "Task: ...". Without it the report uses the first sentence of `goal`. |
| `inputs` | Files or URLs. Each may carry its own `region` masks and expected `text`. |
| `regions` | Named masks: a file path, or `auto:<model AIR>` to generate one on Runware (e.g. BiRefNet). |
| `evaluate` | The dimensions the user chose. Per dimension: `metrics` (ids from `metrics.md`). A metric with a limit (`min`, `max`, `max_px`, `abs_max`, `mean_max`, `p95_max`, `dL_min`, `dL_max`, `aspect_tolerance`) is a pass/fail check; one without is measured only. Both count in the report: recipes are sorted by failed checks, then by average place on the measurements, then by cost. No `mode` is needed (a dimension-wide `mode: gate` or `mode: rank` from older benches still works). |
| `requirements` | What the brief asks, one entry per requirement: `need` (the user's words) and `checks` (labels of the metrics that answer it). `estimate` and `run` warn about a requirement nothing measures or that has no limit; the report lists them. Example: `- { need: "The scene is the reference background", checks: ["Background match", "In the scene (judges)"] }` |
| `calibration` | For judge or aesthetic metrics: how many outputs the user labels. |
| `budget` | `maxPrice`: the most one full run may spend, in USD. The runner refuses to start above it. Same name as the Model Router's price ceiling, but for the whole run, not one request (`max_usd`, the older spelling, still works). |
| `seeds` | Seeds per recipe in the full run (default `[1, 2, 3]`); the smoke round uses the first. |
| `passRule` | How seeds decide a check, per input: `majority` (default), `all`, `any`. A recipe must pass on every input. (`pass_rule`, the older spelling, still works.) |
| `maxModels` | Most distinct models the bench may run (e.g. 3 or 5). The runner refuses more. (`max_models`, the older spelling, still works.) |
| `recipes` | Ids of recipe files to run (or `all`). Each file: `id`, `model` (AIR), `params` (exact schema field names), optional `size` and `mask`, `notes` (every convention translated). |

## Names shared with the Model Router

Where a bench field means the same thing as a field of Runware's Model Router (`model: auto`), it has
the router's name, and the bench's and recipes' own settings follow its camelCase style (`maxModels`, `passRule`,
`recipeDirs`, `judgeWhen`, `maxSide`). Older snake_case spellings (`max_models`, `max_usd`, `price_usd`,
`max_side` ...) still load, and a recipe keeps its fingerprint under either spelling. Metric options
and limits (`mean_max`, `max_px` ...) are unchanged. Shared names: `maxPrice` for a price ceiling in USD, `routing` and its keys in a router recipe,
and **quality, speed and cost** for what is compared (the checks you choose are the quality; speed is
seconds from request to result; cost is USD per output). `requirements` here is the list of what the
brief asks with the checks that measure it; the router's `routing.requirements` is one sentence it
reads to rule models out.

## Recipes: one file each

Recipes live in `recipes/<id>.yaml` next to `bench.yaml`; `bench.yaml` lists the ones to run by id,
or `recipes: all`. Add shared folders with `recipeDirs: [recipes, ../team-recipes]` (earlier
folders win on duplicate ids). Inline recipe dicts still work; `runware-eval recipes extract` moves
them into files.

```yaml
# recipes/ideogram-precise-low.yaml
id: ideogram-precise-low
model: ideogram:4.5@precise-edit
params:
  inputs: { seedImage: $input, referenceImages: [$lighting_ref] }
  positivePrompt: >-
    Relight this product photo using the lighting of the reference image ...
  settings: { quality: low }
  seed: $seed
price: 0.03   # USD per output; the estimate and the budget cap use it until a real cost is measured
notes: >-
  Every convention translated for this model.
fingerprint: 8a2fdbe2577bf114   # written by runware-eval; changes when the request changes
```

- **Self-contained:** prompts are written out in the file. A recipe only expects named slots from
  its bench (`$input`, `$seed`, `$mask`, or media such as `$lighting_ref`); the runner says which
  are missing.
- **Fingerprint:** a hash of `taskType`, `model`, `params`, `size` and `mask`. Renaming a recipe or
  editing its notes keeps it; changing the request changes it, and the runner rewrites the line.
- **History:** every result is keyed by fingerprint + content hash of each image sent + seed. A
  match in any folder under `runs/` (or `--history <folder>`) is copied in instead of paid for again.
- **Sharing:** copy a recipe file into another bench's `recipes/` folder, or point `recipeDirs` at
  a team folder in git.

## Placeholders in recipe `params`

| Placeholder | Becomes |
|---|---|
| `$input` | the input's media URL (uploaded once by the runner, recorded in `media.lock.json`) |
| `$input.width`, `$input.height` | input size, adjusted by the recipe's `size` block |
| `$seed` | the current seed |
| `$prompts.<name>` | a prompt from the top-level `prompts` block |
| `$<name>` | URL of a top-level media entry, e.g. `lighting_ref: { path: refs/light.png }` |

URLs are sent, not media UUIDs: some provider-backed models fail to fetch a UUID.

A recipe's `size` block fits the input to a model's limits: `size: { multiple: 16, maxSide: 2048,
maxMp: 4.19 }`. Check each schema for its own limits and write them here.

## Masks as model inputs

A recipe can send a mask to models that take one (`$mask` in `params`):

```yaml
params: { inputs: { seedImage: $input, maskImage: $mask } }
mask: { edit: logo, polarity: white_is_edit }       # or edit: not(logo); white_is_keep
```

The runner draws the mask at the input's exact size from the named region and uploads it. Check
each model's mask convention in its schema and set `polarity` to match.

Known limit (Ideogram 4.5 Precise Edit, tested): a small *keep* island inside a mostly white mask is
not kept; the model regenerates it. A small *edit* area inside a black mask works pixel-exactly.
Masks are reliable for "change only this", not for "change everything except this".

## Router recipes: `model: auto`

A recipe with `model: auto` sends the request to Runware's Model Router, which picks the model. It is
scored like any other recipe, and the report gets a "Model Router" section: what was picked on each
call, how those outputs did against the checks, and how the same model did when called by name.

```yaml
# recipes/router-auto.yaml
id: router-auto
model: auto
routing:                      # optional; sent as the request's `routing` object
  allowedModels: bench        # shorthand: every model the bench's other recipes name (or a list of 2+)
  preferences: { quality: 5, speed: 0, cost: 0 }   # 0-5 each; leave out for even weights
  maxPrice: 0.10              # USD per request; also used as this recipe's `price` for the budget cap
  requirements: "with audio, 1080p or better"       # plain language, what no parameter can say
params:
  positivePrompt: ...
  inputs: { referenceImages: [$input] }
price: 0.08                   # needed when there is no maxPrice: the dearest model it could pick
```

- **Send only what every candidate accepts.** A value a model cannot take rules that model out, so a
  size, a seed or a model setting narrows the pool. What is left out is filled in by the router (seen:
  a square output from a portrait input, and two resolutions for the same request).
- **One request shape.** A model that wants the product in another field (`seedImage` instead of
  `referenceImages`) cannot be chosen by this recipe. Say so in `notes`.
- **Each seed is one call**, and the router may pick a different model each time. Leave `$seed` out
  unless every candidate has a seed field. Results are cached per seed like any other recipe.
- **No `then` or `post` steps** on a router recipe yet.
- `excludedModels` (a list) is the opposite of `allowedModels`; the two cannot be combined.

## Multi-step recipes

A recipe can continue after its first image:

```yaml
then:                       # a second task on the first output
  model: ideogram:4.5@precise-edit
  params: { inputs: { seedImage: $prev, maskImage: $mask, referenceImages: [$input] }, ... }
post:                       # local steps, no API cost
  - { transferDetail: logo, sigmaPx: 6, featherPx: 6 }      # new light, original fine detail
  - { restore: logo, featherPx: 4 }                          # paste the original pixels back
```

`$prev` is the previous step's image; for a `then` step, `$mask` is redrawn at that image's size.
If a plain recipe with the same first request exists, its image is reused as the first step, so
the only difference between the two recipes is what comes after (fair comparisons, no double cost).

Tested on a relight with a logo: `transferDetail` brought the lettering back with the new light;
`restore` was exact but visibly pasted; a masked `then` pass changed almost nothing. Pixel checks
favour whichever method copies pixels, so judge these with the vision panel and your own eye.

## Metrics: library plus your own

A metric id in `evaluate` resolves to a file: first the bench's `metrics/` folder (or the folders in
`metricDirs`, in order), then the runner's library. A bench file with a library id overrides it.
`task_specific` + `name: x` is the older spelling of `id: x` and still works. Every score records the
metric's fingerprint (a hash of its file), so a changed metric is visible in the results.

## Other optional fields

- `label:` on any metric gives it a readable column name in the report.
- `title:` (top level) is the report's heading.
- `judges:` (top level) is the vision-model panel; metrics use it via `judges: $judges`.
- `refs: [<media name>]` on a `vlm_*` metric shows those references to the judges.
- `report: { x: cost, y: "Colour" }` picks the trade-off chart's axes, by metric label or `cost`.
  Default: cost against the first colour check.
- Avoid YAML 1.1 surprises: keys like `on:`, `off:`, `yes:` are read as booleans by many parsers.
  The runner corrects them, but other tools may not.

## Example

```yaml
goal: "Add a soft contact shadow. The product and the backdrop colour must not change."
inputs:
  - { path: inputs/sneaker_side.png, regions: { product: auto:runware:112@5 } }
  - { path: inputs/boot_front.png,   regions: { product: masks/boot_front.png } }

evaluate:
  pixel_shift:
    metrics:
      - { id: size_aspect }
      - { id: phase_correlation, max_px: 1 }
  deviation:
    metrics:
      - { id: deltaE2000_region, region: product, mean_max: 1.0, p95_max: 2.0 }
      - { id: ssim_region, region: product, min: 0.98 }
      - { id: deltaE2000_region, region: not(product), mean_max: 1.5 }
  prompt_adherence:
    metrics:
      - { id: task_specific, name: contact_shadow, below: product, dL_min: 8, dL_max: 30 }
  aesthetics:                  # no limits: measured, and used to place the recipes
    metrics:
      - { id: vlm_rubric, judges: [3 vision models from different providers] }
      - { id: pairwise_human }

calibration: { labelCount: 8 }
budget: { maxPrice: 5.00 }
seeds: [1, 2]

recipes:
  - id: precise-edit-high
    model: "ideogram:4.5@precise-edit"
    params: { quality: high, positivePrompt: "<shadow-only prompt>" }
    mask: { region: product, polarity: edit_is_white, use: not(product) }
    notes: "maskImage: white = edit, black = preserve. Pass the inverted product mask."
  - id: precise-edit-very-low
    model: "ideogram:4.5@precise-edit"
    params: { quality: very_low, positivePrompt: "<shadow-only prompt>" }
    mask: { region: product, polarity: edit_is_white, use: not(product) }
    notes: "Cheapest tier of the same model. Tests whether pixel restoration holds at low quality."
  - id: nano-banana-2-1
    model: "google:nano-banana@2.1"
    params: { positivePrompt: "<shadow-only prompt>" }
    notes: "No mask input. Preservation relies on the prompt."
```

The model IDs above are examples. Always confirm `live` status, `x-modes` and field names through
`model_schema` before writing a recipe.
