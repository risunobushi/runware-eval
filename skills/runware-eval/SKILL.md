---
name: runware-eval
description: >
  Set up a reproducible test bench that compares Runware models and settings against the user's own
  goal and inputs. Use when the user says "which model is best for my use case", "compare these
  models", "benchmark", "A/B test models", "evaluate outputs", "did the product change", "measure
  drift / fidelity / pixel shift / aesthetics", "set up a testing bench", "re-test when new models
  ship", or "check my migrated pipeline didn't regress". `/runware-eval help` explains it and lists its
  commands. Not for a one-off generation; for that use
  the outcome skill (edit-image, product-photography, ...).
---

# Runware eval

Turn "which model is best for this?" into a bench file that anyone can re-run: the user's inputs, a
set of recipes (model × settings × prompt × mask), and the metrics that measure *their* definition
of good. The agent's job is setup and judgement. Execution belongs to the runner, not to a chat loop.

**Core rule: the user decides what "good" means; the catalog decides what is possible.** Never pick
metrics before asking, and never claim what a model can or cannot do without reading its schema.

## Help: `/runware-eval help`

If the skill is called with the argument `help` (or the user only asks what this skill does or how to
use it), reply with the text below, adapted to what is in the working folder, and stop. No preflight,
no installs, no intake questions, no catalog calls. You may list the benches found in the working
folder (path and goal in a few words) and say whether the Runware CLI and uv are ready, if you can
tell from a read-only check.

> **runware-eval** answers "which Runware model is best for my task?" with a bench you can re-run:
> your inputs, a set of recipes (model, settings, prompt, mask) and the checks that measure your
> definition of good. Images, video, 3D models, upscaling, background removal, masking, vectorizing,
> captions and text are supported.
>
> **To start**, describe the task in plain words, e.g. "which model is best for relighting product
> photos?". I will then:
> 1. check the Runware CLI and uv, install what is missing, and ask you to sign in once;
> 2. ask what to evaluate (deviation, pixel shift, identity, text and brand, prompt adherence,
>    aesthetics, technical quality), your budget and how many models to test;
> 3. propose checks, find candidate models, and write one recipe file per candidate;
> 4. show a cost estimate, run a smoke round, then the full run;
> 5. hand you one HTML report, where you can also label outputs blind to see how the checks compare
>    with your eye.
>
> **Runner commands** (`uv run --project <runner> runware-eval <command> bench.yaml`):
>
> | Command | What it does |
> |---|---|
> | `estimate` | cost per recipe, each recipe's parameters checked against its model's schema, and models that changed since the last run; before anything is paid |
> | `run --round smoke` or `--round full` | generate, score and report |
> | `score`, `report` | re-score or rebuild the report from saved results; no login needed |
> | `calibrate --labels <file>` | take labels exported from the report: agreement and suggested thresholds |
> | `label` | a separate blind labeling page covering every draw |
> | `metrics list`, `metrics plan` or `metrics control` | the metrics this bench can use; the table of this bench's checks for the user to choose from; test them on unchanged inputs |
> | `recipes list` or `recipes extract` | recipe files and their past runs |
>
> Spend is capped by `budget.maxSpend` in `bench.yaml`, and an interrupted run can be run again
> without paying twice.

Do not write a dollar sign directly followed by a digit anywhere in this file: the agent harness
replaces such tokens with the skill's arguments. Write prices as `0.006 USD`.

**Use the Model Router's words** where they fit, with the user and in `bench.yaml`: quality, speed and
cost for what is compared, `maxPrice` for a price ceiling on one request, `requirements` for what the result must
meet. A user who has used `model: auto` should not have to learn a second vocabulary.

## Step 0 — Preflight: Runware CLI and uv, before anything else

The bench needs both, every time (a `help` call is the one exception, see above). Check them before
any other step, including the existing-bench question, and do not continue until both are ready. Do not substitute guessed REST calls, web
searches, or model knowledge from memory.

- **Runware CLI**: the catalog (search, schemas, pricing, examples), uploads of local files at full
  size, and the login the runner uses. One sign-in covers everything.
- **uv**: runs the bench runner in its own isolated environment, on a pinned Python 3.12 that uv
  downloads if needed. Nothing is installed into the user's Python (they need none), so no admin
  rights, PATH changes or dependency clashes.

Every catalog question goes through the CLI, and the runner does the paid work. Both work in any
agent with a shell, and nothing needs a restart.

### 1. Check both (read-only)

| | Ready when | Otherwise |
|---|---|---|
| CLI | `runware auth status` prints a table whose `Status` row is `valid` | Command not found: missing. Any other `Status` value (e.g. `not configured`): installed, not signed in. |
| uv | `uv --version`, or `~/.runware-eval/tools/uv --version`, prints a version | Neither found: missing. |

Read-only looks at the working folder (e.g. for an existing `bench.yaml`) are fine during this step.
Show the user this status in two lines, then fix what is missing.

### 2. Install what is missing, yourself (the user approves each command)

Neither needs a restart or admin rights.

- **CLI**
  - Windows with scoop: `scoop bucket add runware https://github.com/Runware/scoop-bucket.git` then
    `scoop install runware` (adding a bucket needs git: `scoop install git` first if it is missing).
    Without scoop, ask whether to install scoop first.
  - macOS: `brew install --cask runware/tap/runware`
  - Linux: `curl -fsSL https://cli.runware.ai/install.sh | sh`
- **uv**: install it self-contained in one folder, without changing PATH or adding an updater
  (deleting the folder removes it). The installers ask nothing.
  - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$HOME/.runware-eval/tools" sh`
  - Windows (PowerShell): `$env:UV_UNMANAGED_INSTALL="$HOME\.runware-eval\tools"; powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - Then call it as `~/.runware-eval/tools/uv`. If the user already has uv (or prefers `scoop install uv` /
    `brew install uv`), use that instead.

If a freshly installed command is not found, call it by its full path (e.g. `~/scoop/shims/runware`)
rather than asking for a restart. If an install fails, show the user the error and stop there.

### 3. The one step only the user can do

If the CLI is not signed in: ask them to open a **separate terminal**, run `runware auth login` and
paste their API key at the prompt (runware.ai → dashboard → API keys), then say "continue". Never ask
for the key in the chat; never use `--key`.

While they do this, ask one thing, so the wait is not wasted: if the folder already has a bench, the
existing-bench question below; otherwise Step 1 question 1 (goal and inputs). Nothing else.

### 4. Re-check

When they say continue, run the checks in part 1 again. Proceed only when both are ready.

Urgency ("I'm in a hurry", "just get going") is not declining. Only if the user explicitly declines
the CLI: read the public catalog (`https://runware.ai/docs/models/index.json` and each model's
`schema` URL) and say the bench can be designed but not run until they sign in. Never ask for a
`.env` file.

The runner uploads local inputs itself (once, through the CLI) and records their URLs; nothing to do
by hand.

## Existing benches: mention, then ask

If you find a `bench.yaml` (or earlier outputs or reports) in the working folder, do not assume it is
what the user wants, and do not summarise its results or plan its next round. Say in one or two
lines that it exists (path, its goal in a few words, whether it has results), then ask:

- **Start a new bench** (default for a new request): leave the existing one untouched.
- **Re-run or extend the existing bench**: new inputs, recipes or draws on the same goal.
- **Review the existing results** first.

In the same message you may ask which input files to use (and whether they are the ones already in
the bench). Then **wait for the answer before doing anything else**: no uploads, no further
intake. (Step 0 has already run: the tools are ready whichever option they choose.) Describe results only if they choose to review them.

## Step 1 — Intake: ask what to evaluate

Ask in this order and wait for answers. If the user has already answered part of a question, ask
only the rest. If they answer several at once in free text, map their words onto the table below,
**show the table with their choices marked**, and ask them to confirm. Never skip showing the table:
it is how users discover dimensions they had not thought of.

1. **The goal** in one sentence, and the inputs (files or URLs). How many, and how varied.
2. **What to evaluate** — present the dimensions as a multi-select. Do not pre-select:

   | Dimension | The question it answers |
   |---|---|
   | Deviation | Did it change what it should not? (colour, structure) |
   | Pixel shift | Did anything move, warp, crop or resize? |
   | Identity | Is it still the same face / product / character? |
   | Text & brand | Is the copy and logo exactly right? |
   | Prompt adherence | Did it do what the brief asked? |
   | Aesthetics | Is it good? (subjective — needs calibration) |
   | Technical quality | Is it clean? (sharpness, artefacts, seams) |

   Cost, speed and failure rate are always measured. Say so.
3. **Follow-ups only for the chosen dimensions**: which region must stay fixed (do they have masks,
   or should the bench generate them), expected text, reference identity. Do not ask the user to
   choose between "gate" and "rank", and do not use those words with them: every measurement counts
   in the report either way (see Step 2, point 6).
4. **Budget and size:** the most one full run may spend, in USD (`budget.maxSpend` in `bench.yaml`),
   and the **maximum number of models**
   to test (e.g. 3 or 5; it cuts time and spend). Write it as `maxModels` in `bench.yaml` and
   propose exactly that many in Step 3; the runner refuses more. Draws: 1 in the smoke round, **3 in
   the full run** (`draws: 3`), so one unlucky or lucky generation does not decide: each
   check is judged by `passRule` (default `majority` of draws, per input; also `all` or `any`).
   A draw is one more generation of the same request. **Do not put a seed in a recipe**: with no
   seed every model generates on a random one, so three draws are three different outputs whether
   or not the model has a seed field. Only if the user asks for runs that reproduce the same
   pictures, add `seed: $seed` (the draw's number) to the recipes of models that have a seed field,
   and tell them the other models stay random.

## Step 2 — Turn the brief into checks

Metrics are files, like recipes: a curated library ships with the runner (listed in
`references/metric-catalog.md`, generated from the code), and a bench can add its own in `metrics/`
(or shared `metricDirs`). `uv run --project <runner> runware-eval metrics list bench.yaml` shows
what this bench can use.

**Start from the brief, not from the library.** The library covers common cases (a product that must
not change, video stability, mesh facts, outlines of cut-outs and masks, vector files, text). Many briefs are about something else (an illustration
style, a layout, a character across several images), and even a familiar brief usually has one
requirement no stock metric answers. A requirement without a check is invisible in the report: a
recipe can fail it completely and still come first. So, before choosing any metric:

1. **List the requirements.** Take the goal apart, clause by clause, into statements an output either
   meets or does not: what must stay, what must change, what must appear, what must not appear. Add
   the ones the inputs imply: every file the user supplied is there for a reason (a reference
   background means "the scene is this background"; a style reference means "the output has this
   style"). Add "the task was done at all" for every change the brief asks for.
2. **Give each requirement a measurement of that requirement**, not of something near it. This is
   your job, not the user's: you find the requirements in the brief and the inputs, and every one of
   them gets a check. Use a library metric when one measures it; otherwise write a metric for it
   (below). The library cannot cover every requirement a brief can have, by design: writing the
   missing metric is the normal path. A requirement with no check is a mistake in the bench, and
   `run` refuses to start with one. Do not leave a requirement to the vision judges alone when pixels
   can answer it; use the judges for what only an eye can answer, and as the cross-check from a
   different family.
   **A requirement an output either meets or does not is a yes/no check.** "Reads as one real
   photograph", "nothing was added", "the logo is readable": ask the judges a yes/no question
   (`vlm_checklist`, `vlm_same_object`). These pass or fail by themselves, with no number to set: the
   check passes when, on every question, more judges say yes than no. Write each question so it asks
   one thing the judges can see. Two things in one question ("a real photo, with light and shadow
   agreeing") fail together, and a question the judges cannot answer reliably (left versus right, in
   testing) fails good outputs: leave that to a pixel metric and do not ask it.
3. **Try lazy outputs in your head.** For each of these, name the check that fails it: the input
   returned unchanged; the subject pasted on top with nothing else done; the right subject in the
   wrong scene or style; a beautiful image that ignores the brief. If one of them fails nothing, a
   requirement is missing or has no limit.
4. **Write it down** as `requirements:` in `bench.yaml`: each need in the user's words, with the
   labels of the checks that answer it. `estimate` and `run` print what is uncovered before anything
   is paid, and the report shows the list, so a hole is visible to the reader instead of hidden.

Writing a metric is normal work here, not a last resort. Think in what can be computed from the
input, the output, their masks and any reference image (`media(pair, "<name>")` reads one): colour
distributions and palettes, edges and line weight, texture and flatness, layout and position of
masked regions, similarity of a region to a reference, change over frames. For an illustration
bench, for example: distance between the output's palette and the style reference's, edge density
and stroke width against the reference, number of flat colour areas, the character's proportions
across images. Name what the number means in the `description`, and test it (controls, below)
before trusting it.

Then load `references/metrics.md` for how to choose among existing metrics, and select per dimension:

1. Drop metrics whose `needs` the user cannot supply, and tell them which dimension lost coverage.
2. Prefer trust order: deterministic > learned > judge > human.
3. Add one cross-check from a different `family` for every dimension, so disagreement is visible.
4. Measure pixel shift before deviation (misalignment inflates ΔE).
5. Aesthetics or any judge metric: plan the calibration step (Step 5) — the user labels outputs
   good or bad, blind; metrics that disagree with them are flagged, and the blind pairwise ranking
   becomes the ranking that counts.
6. **Limits and places both always count; the user does not choose a mode.** Do not write `mode:`
   in `bench.yaml`. A metric with a limit next to it (`min`, `max`, `mean_max`, ...) is a pass/fail
   check; a metric without one is only measured. The report sorts recipes by failed checks, then by
   average place across the dimensions (place 1 = best on a measurement, averaged inside each
   dimension, then across dimensions), then by cost. So:
   - **Do not invent limits for numeric checks, and do not ask the user for them.** Write the check
     without a limit. The runner sets it from the first full run and freezes it in `limits.yaml` next
     to `bench.yaml`: the median of the recipes' results, moved towards "worse" by a margin (the larger
     of the typical spread between draws and the metric's `tolerance`, its smallest difference that
     counts). An output fails when it is worse than the typical recipe by more than a re-roll explains.
     The reason: there is no "nothing changed" baseline. A model changes pixels just by encoding and
     decoding the picture, and nobody can measure that round trip for a closed model, so what real
     models return is the only baseline. If every recipe is poor, the typical one still passes: that
     is the ceiling of what models can do on this brief, not a fault of the bench.
   - Write a limit into `bench.yaml` yourself only when the brief states one ("at most 2 seconds",
     "under 0.10 USD", "exactly the input's size") or the user asks for one. A limit in `bench.yaml`
     always wins over `limits.yaml`. `limit: none` on a check keeps it measured only.
   - After the first full run, tell the user which limits were set and how (the run prints them, the
     report lists them under caveats, `limits.yaml` holds the `from` line of each). If the user wants
     one changed, edit its value in `limits.yaml`, add to its `from` line that the user set it and
     why, and run `score` again. Limits never move by themselves after that, so recipes added later
     are held to the same line.
   - The frozen limits hold for the inputs they were set on. When the user brings new inputs (a held-out
     set, another product line), make a new bench folder for them, do not reuse `limits.yaml`, and report
     the measurements next to the pass counts (see "Limits set from the first full run" in
     `references/bench-format.md`).
   - Yes/no judge checks need none of this: they pass or fail from the first run.
   - The smoke round sets no limits (one draw, one input): look at its outputs for broken recipes,
     not at pass and fail.
   - Say it to the user in plain words: "these are the limits an output must meet; everything else is
     measured and used to place the recipes". A failed check counts against a recipe in the report; it
     does not remove the recipe from the run or from a later step.
   - A metric only places recipes when its `META` has a `direction` (`lower`, `higher` or
     `closer_to_zero`). Set it in every metric you write.

**The user chooses the checks.** When the checks are written into `bench.yaml`, run
`runware-eval metrics plan bench.yaml` and show its table to the user as it is: every check you came
up with, the requirement it answers, whether its metric comes from the library or was written for
this bench, how far it can be trusted, and what makes it fail, followed by one line per check on
what it measures (and the judges' questions, word for word). Ask which ones to apply; they can keep
all, drop some, or ask for others. Then:

- Remove the checks they dropped from `evaluate` and from `requirements`.
- If that leaves a requirement with no check, keep the requirement and write the choice down:
  `- { need: "...", checks: [], notMeasured: "dropped by the user: judged by eye" }`. The report lists
  it as left out by choice. Never use `notMeasured` for a requirement you did not manage to measure.
- Show the table again after any change, and get a yes before continuing.

**To write a metric**: a file in the bench's `metrics/` folder with a `META` dict and a
`compute(pair, opt)` function, following the contract in the runner's `metric_api.py`. Set
`direction` (`lower`, `higher` or `closer_to_zero`: without it the check cannot get a limit or place
recipes) and `tolerance`, the smallest difference in this metric's unit that anyone would care about
(2 px, 1 L*, 0.02 of an overlap): it is the least margin a limit set from results will have. Set `kind`
honestly: `preserve` (an unchanged output must pass), `change` (the task asks for change, so an
unchanged output must fail) or `info`. Then:

1. Show the user the code and get a yes: metric files run on their machine.
2. Run `runware-eval metrics control bench.yaml`. It scores every input against an unchanged copy of
   itself; a control that goes the wrong way means the metric or its threshold is broken. For a
   metric that compares with a reference image, also check by hand that the reference scores as a
   match and an unrelated image does not.
3. Never edit the runner's library to add a bench-specific metric.

Four worked examples of bench-specific metrics (written for a relighting bench) are in the repo's
`examples/metrics/`: copy one as a starting point.

## Step 3 — Find candidates in the catalog

These are free, read-only calls: you may start them as soon as the dimensions are confirmed, in
parallel with metric sign-off. Propose recipes only after sign-off. Add `-F json`, and keep stderr
out of what you parse (`2>/dev/null`): a `Showing N of M results` footer goes there.

1. **Search:** `runware model search --source official --capabilities <cap> --limit 100`. Tags are
   `io:<from>-to-<to>` (e.g. `io:image-to-video`, `io:image-to-3d`, `io:image-to-text`,
   `io:text-to-text`) and `op:<operation>` (e.g. `op:edit`, `op:inpaint`, `op:upscale`,
   `op:remove-background`, `op:mask`, `op:vectorize`, `op:caption`); repeat `--capabilities` to combine. If unsure of a tag, search without
   it and read the results' `capabilities`. The default limit is 20 and truncates silently.
2. **Status and price:** `runware model pricing <air> -F json` gives `status` (keep `live` only) and
   the model's slug (`model`). It only lists a few example configurations; the real rates per unit
   and tier are in the public schema, `info.x-pricing.rates`. Drop any model whose pricing or schema
   call fails, even if search lists it.
3. **Schema:** `runware model schema <air> -F json` (`requestSchema.properties`): input media under
   `inputs`, model options under `settings` and `providerSettings.<provider>`. Use only these fields,
   with their exact names, and **read their descriptions**: preservation behaviour, quality tiers and
   mask conventions live in prose. Accepted input combinations are `info.x-modes` in the public
   schema, `https://runware.ai/docs/models/<slug>/schema.json` (the slug, not the AIR; fetch with
   curl, as some clients are refused). `runware model examples <air> -F json` shows a real request
   when the shape is unclear.
4. **Defaults that change cost or results:** note them per recipe and set them deliberately. Seen so
   far: audio on by default (costs more), prompt rewriting on by default (`promptExtend`,
   `promptUpsampling`, `enhancePrompt`: hurts reproducibility), fixed duration steps or minimums, and
   quality or speed modes.
5. **Propose recipes, not just models:** quality tiers, prompt variants and mask variants of strong
   candidates; a cheap tier of a good model is a real contender. Size the list to the budget:
   recipes x inputs x draws x price must fit the cap for the full run, not just the smoke round.
6. **Offer the Model Router as a baseline.** Runware's Model Router (`model: auto`) picks a model
   from the request alone. Ask the user whether to add a router recipe (see "Router recipes" in
   `references/bench-format.md`): `routing.allowedModels: bench` makes it choose among the models
   under test, and a second recipe with `preferences: { quality: 5, speed: 0, cost: 0 }` shows what
   the weights change. The report then says whether the router's pick passes the brief's checks, and
   which model to call by name if it does not. It counts as recipes for the budget, not as a model
   for `maxModels`.

## Step 4 — Normalise and write the bench

Map each recipe's parameters from its own schema. Record every convention you had to translate in a
`notes` field. The ones that silently break benches:

- **Mask polarity** (edit tasks): some models use white = edit, others white = keep.
- **Reference inputs** (identity, style, product): field names, how many references, and the
  strength or weight scale differ per model. Do not assume one model's scale carries over.
- **Size and aspect**: allowed dimensions differ; note any model that snaps or pads.

Write each recipe as its own file in `recipes/<id>.yaml` (self-contained: prompts written out, notes
on every translated convention), and list them by id in `bench.yaml`, following
`references/bench-format.md`. Before creating a recipe, run
`uv run --project <runner> runware-eval recipes list bench.yaml`: if a recipe for the same model and
settings already exists in the bench's recipe folders (or a team folder in `recipeDirs`), reuse it
instead of writing a near-duplicate. The bench is the deliverable: it must re-run later without an
agent, and adding a model must mean adding one recipe file.

## Step 5 — Cost, smoke round, full run, report

Commands that only read results (`score`, `report`, `label`, `calibrate`, `metrics control`) need no
Runware login: anyone with the run folder can re-score it and rebuild its report; vision judges then
use their cached answers. And the report itself is one HTML file anyone can open in a browser.

The runner does the paid work. Do not `pip install` it. Run it through uv, which builds an isolated
environment on first use (about a minute) and reuses it afterwards:

`uv run --project <runner> runware-eval …`

`<runner>` is the `runner/` folder of the runware-eval repo. Installed as a plugin, it sits next to
`skills/`: two levels above this skill's base directory, then `runner`. Otherwise look for a
`runware-eval/runner/pyproject.toml` in the working folder. If the repo is not on disk at all,
use `uvx --from "git+https://github.com/risunobushi/runware-eval#subdirectory=runner" runware-eval …`
instead. The runner signs in with the CLI login.
Every command takes `--out <folder>`; results there are cached, so nothing is ever paid for twice.

1. **Estimate:** `uv run --project <runner> runware-eval estimate bench.yaml --round smoke`. Costs are *measured* averages from
   earlier runs in that folder, otherwise the highest *listed* price in the model's schema. Runware has
   no reliable dry-run (the `X-Runware-Dry-Run` header executed and billed in testing), so never
   promise a free price check. Show the user the table and get a yes.
   `estimate` and `run` also print two things, both read from the models' published schemas:
   - **Parameter check.** Lines marked `x` (a field the model does not have, a value it does not allow)
     stop `run` before anything is paid: fix the recipe file. Runware would have run and billed the
     request at the model's default. Lines marked `!` (a field the schema calls required, a rule between
     fields) do not stop it: the schema is sometimes stricter than the API, so tell the user and let the
     smoke round decide. Use `--skip-model-check` only when the user confirms the schema is wrong.
   - **Models that changed since this bench last ran** (status, price, fields, defaults). Read the lines
     to the user. Cached results from before the change are kept and marked in the report; offer
     `run --regenerate-changed` (paid) when the change touches what the bench measures. A first run has
     nothing to compare with and prints nothing.
2. **Smoke round:** `uv run --project <runner> runware-eval run bench.yaml --round smoke` (first input, first draw, every
   recipe). It records real cost and speed per task, masks every output and writes the report.
   Look at every output for inverted masks, cropping and ignored instructions; fix recipes first.
3. **Full run:** `uv run --project <runner> runware-eval estimate bench.yaml --round full` (now with measured costs), then, with
   the user's OK, `uv run --project <runner> runware-eval run bench.yaml --round full`. It stops before starting if the projected
   total would pass `budget.maxSpend`.
4. **Report:** `uv run --project <runner> runware-eval report bench.yaml --round full --notes notes.json` rebuilds `report.html`:
   the best recipe and what it still misses, trade-off chart, check-by-check table, before/after slider with a colour-drift heatmap,
   region crops, gallery and all data, in one file. Put your reading of the results (what passed, what
   is misleading, what to change next) in `notes.json` as `findings` and `caveats`. Open each note with
   a short `<b>bold claim</b>` (under ten words): the report lists only that line and folds the rest
   behind a click, so the claim must stand alone and the rest should be one or two sentences. Hand the user the
   report, not loose images.

5. **Calibrate against the user's eye** (after the smoke round, and again after the full run). The
   report has the labeling built in: under "Your labels" the user marks outputs good or bad and picks
   the better of random pairs, with recipe names hidden. The page keeps the labels in their browser
   and shows at once how often each check agreed with them, the threshold that would agree best, which
   rank metrics order their good above their bad, and their own ranking (Bradley-Terry), with "Your
   pick" next to the headline. No command is needed for that. You cannot see labels that live in
   their browser: to act on them, ask the user to press "Export labels.json" and run
   `runware-eval calibrate bench.yaml --round <r> --labels <file>`, which prints the same analysis
   and stores the labels with the run, so the rebuilt report opens with them. Show the suggestions;
   change `bench.yaml` only with the user's yes. Below about 20 labels, call the suggestions hints.
   The report shows and offers for labeling each recipe's best draw (the one that fails the fewest
   checks); `runware-eval label` still builds a separate page that covers every draw.
   Keep the three layers apart when you report: measured values are shared evidence; pass or fail
   is this brief's thresholds; labels and rankings are this user's preference. The report shows
   "Your pick" beside "Best against this brief's checks"; when they disagree, say so and do not
   pick one for the user.

Vision-model checks run in `score` as the second stage of a funnel: only outputs that fail at most
`judgeWhen.maxFailedChecks` pixel checks are judged, with one combined call per judge (about
0.006 USD per judged output; cached; `--no-judges` skips them). When picking metrics in Step 2, give the
judges only questions no pixel check can answer. 3D outputs (GLB) and video
outputs (MP4) need nothing extra: the runner renders or reads them into images first, see the 3D and
video sections of `references/metrics.md`. For video recipes set `taskType: videoInference`, pass the
start image in `inputs.frameImages`, switch audio and prompt rewriting off, and give `price`
(USD per output; video is priced per second). The run buys a product outline for five frames of every
clip (about 0.003 USD per clip), which the product checks (`video_outline_hold`, `video_product_area`,
`video_product_drift`) read; judges get the first, middle and last frame, so write their questions
about "the video". Every brief that says the product must stay the same needs at least one of the
product checks: the frame-wide video checks do not look at the product. Upscalers, background removers, masking models,
A model the user trained or deployed on Runware Serverless is benched like any other: a recipe with
`taskType: serverlessEndpoint` calls the app's endpoint (see "Your own model on Runware Serverless" in
`references/bench-format.md`), so "is my fine-tune better than what I started from?" is the same bench
with one more recipe. Keep the inputs it was trained on apart from the inputs it is tested on, and say in
the report which is which. Upscalers, background removers, masking models,
vectorizers, captioners and text models are benched the same way: set the recipe's `taskType`
(`upscale`, `removeBackground`, `imageMasking`, `vectorize`, `caption`, `textInference`) and pick the
checks from the matching section of `references/metrics.md`; what each recipe sends is in "Task types"
in `references/bench-format.md`. Three things to settle with the user for these: a background-removal
or masking bench needs a **reference outline** they trust for each input (ask for it, or make one and
have them correct it; never from a model under test); a text bench needs its **inputs as text files**
and, per input, what a good answer must contain or must not say; and text answers are **judged by text
models**, so keep the models under test off the judge panel. Audio, prompt enhancement and ControlNet
preprocessing are not supported yet: say so instead of improvising. A check that could not run on an
output shows as *not run* in the report, with the reason. Say so; never present it as passed.

**Before reporting, check the limits and the standings against the outputs.** A check that every
recipe fails, or one that passes something visibly wrong (e.g. a hue-only backdrop check passing a
black backdrop), is mis-specified: fix its limit or remove the limit, and say so in the caveats. If the
report's best recipe is visibly not the best (it places well by doing nothing, or one dimension has no
limit), add the missing limit rather than explaining it away. A report whose headline says "No
pass/fail limits are set" means Step 2, point 6 was skipped.

## Red flags — stop and correct

| Thought | Reality |
|---|---|
| "I already know the right metrics for this" | Ask first. Another user with the same inputs may care about different things. |
| "No model can preserve pixels, so I'll build a workaround" | Read the schemas first. Some models restore unchanged pixels by design. |
| "I'll search the whole catalog for edit models" | Without `--source official` the search includes community fine-tunes. Filter by source and capability. |
| "I'll write custom scripts for this user" | Write `bench.yaml`. A one-off script is not a bench. |
| "I'll loop single API calls over the whole grid in chat" | The runner executes, with caching, budget and cost records. |
| "I'll dry-run it to get a free price" | Dry-run is unreliable on Runware. Estimate from measured smoke costs, and say which numbers are listed. |
| "I'll write the request from memory" | Read the model's schema with `runware model schema` first. Field names differ per model. |
| "Inputs are URLs / already uploaded, so I can skip one of the two" | Step 0 needs both every time: the runner uses the CLI login and runs through uv. |
| "I'll add this check to the runner's code" | Write it in the bench's `metrics/` folder, show it, run the controls. |
| "The numbers look plausible, so the checks work" | Run `metrics control` and look at the outputs. Plausible numbers hid three broken checks in testing. |
| "I'll put the recipes inline in bench.yaml" | One file per recipe in `recipes/`, so they can be shared and matched by fingerprint. |
| "I'll `pip install` the runner" | Never into the user's Python. Run it through uv. |
| "I'll just print the install command for the user" | If you can run it, run it. Leave the user only the sign-in. |
| "I'll ask for the key so I can run `runware auth login --key`" | Never. The user signs in at the CLI prompt in their own terminal. |
| "There's already a bench for this; I'll pick up where it left off" | Mention it and ask. A new request is a new bench unless the user says otherwise. |

## Quality bar

- The user chose the dimensions; every metric traces back to one of them.
- Every recipe's capabilities were verified in its schema, not assumed.
- Mask and other conventions are recorded per recipe.
- Cost was estimated and approved before any paid call.
- `bench.yaml` re-runs without an agent.

## Related skills

`runware-models` (catalog lookup), `runware-run` (execution contract), `edit-image`,
`product-photography`, `character-consistency`, `text-in-image` (the outcomes this bench evaluates),
and the `migrate` skills (use a bench to prove a migrated recipe did not regress).
