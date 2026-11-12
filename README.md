# runware-eval

A test bench for [Runware](https://runware.ai) models. Tell your agent what you're making and what
"good" means for you. It finds the Runware models and settings that can do the job, picks the
metrics that measure your definition of good, and writes a `bench.yaml` you can re-run whenever a
new model ships.

> Status: the skill sets up the bench; the runner (`runner/`) estimates, runs, scores and reports it,
> with pixel checks, OCR checks, a panel of vision-model judges, blind human labeling and calibration.
> Tested on Windows; macOS and Linux are untested.

## Install

**Claude Code** (plugin):

```
/plugin marketplace add risunobushi/runware-eval
/plugin install eval@runware-eval
```

In Claude Code, `/runware-eval help` explains the skill and lists the runner commands.

**Any other agent with a shell:** copy `skills/runware-eval/` to where your agent loads skills
(`.claude/skills/`, `.cursor/skills/`, `.agents/skills/`).

The skill sets up the two tools it needs on first use, with no admin rights and no restart: the
[Runware CLI](https://github.com/runware/runware-cli) (catalog, uploads, and the one sign-in:
`runware auth login`) and [uv](https://docs.astral.sh/uv/) (runs the bench runner in its own
environment).

## Use

Ask your agent something like *"Which Runware model is best for adding a contact shadow without
changing my product?"* The skill will:

1. check the Runware CLI and uv, install what is missing, and ask you to sign in once;
2. ask what you want to evaluate (deviation, pixel shift, identity, text, prompt adherence,
   aesthetics, technical quality), with cost and speed always measured;
3. pick metrics from the library (`references/metric-catalog.md`), or write a new one with you;
4. find candidate models in the catalog with the CLI and read their schemas;
5. write `bench.yaml` and one file per recipe, and estimate the cost;
6. run a smoke round, then the full run, and hand you a single HTML report.

## Runner

Runs through [uv](https://docs.astral.sh/uv/), so nothing is installed into your Python and no admin
rights are needed. Needs the Runware CLI signed in (`runware auth login`).

```
uv run --project runner runware-eval estimate bench.yaml --round smoke
uv run --project runner runware-eval run      bench.yaml --round smoke   # first input, first draw
uv run --project runner runware-eval run      bench.yaml --round full    # stops before passing the budget
uv run --project runner runware-eval report   bench.yaml --round full --notes notes.json
uv run --project runner runware-eval calibrate bench.yaml --round full --labels labels.json   # labels exported from the report
```

**Outputs.** Images are scored directly. Upscaled pictures are also read at their own size; a
background removal or a mask is compared with a reference outline; an SVG is rendered and its file read
(shapes, nodes, embedded bitmaps); captions and text answers are checked as text and by the judge panel. 3D models (GLB) are rendered to the view that matches the
input photo; videos (MP4) are read into frames: the first frame is compared with the input,
video checks (motion, frozen frames, scene changes, flicker, colour drift, texture stability, sharpness
over time, black bars) read the whole clip, and product checks (outline, size, colour make-up) and the
judges read five frames spread over it, each with its own product outline. The report
plays two clips side by side on one clock and draws each per-frame measurement over time. Metrics are one file each: a library ships with the runner
(`runner/runware_eval/metrics_lib/`), a bench adds its own in `metrics/`, and `examples/metrics/` has
four written for one bench.

A bench lists what the brief asks (`requirements`) and which checks answer each part. A requirement
nothing measures stops a paid run (the agent writes a metric for it, or the user leaves it out on purpose),
one with no limit is printed before a run, and both are shown in the report, so a hole in
the bench is visible instead of silently missing from the standings. When no stock metric measures a
requirement, the agent writes one for the bench.

The report keeps three things apart. **Measured values** are the same for every user and every re-run.
The **verdict** ("best against this brief's checks": recipes that did not do the task last, then fewest failed checks, then best average place on
the measurements, then lowest cost, with the
checks it still misses named) depends on the bench's limits (see **Limits** below), which are a judgement
for one brief. **Your pick** appears once you have labeled outputs: it is your preference, shown beside
the verdict and never applied to the bench. When the two disagree, the report says so.

**Labeling is in the report.** Under "Your labels" you mark outputs good or bad and pick the better of
random pairs, with recipe names hidden. Labels stay in your browser; agreement with each check, the
limit that would agree best and your own ranking are computed in the page as you click. "Export
labels.json" hands them to `runware-eval calibrate` or to a colleague, who can import them.

**Draws.** Each recipe runs `draws` times on each input (3 by default, 1 in the smoke round). No seed
is sent unless a recipe asks for one, so every draw is a new generation on the model's own random seed,
whether or not the model has a seed field. A check passes when it passes on most draws. Draws that come
back as the very same file are called out in the report.

**Limits.** There is one place a limit comes from, and nobody types it. A yes/no requirement is a question to the judges and passes when most
say yes. A numeric check gets its limit from the bench's first full run: the median of the recipes' results,
moved towards "worse" by the larger of the spread between draws and the metric's smallest difference that
counts. There is no "nothing changed" baseline to hold a model to (encoding and decoding a picture already
changes it, and a closed model's round trip cannot be measured), so the typical result of real models is
the baseline. The limits are frozen in `limits.yaml` with a line on where each came from, and the report lists
them. Two things can change one, both on your word. A number the brief states ("under 2 seconds") is written
next to the check in `bench.yaml` and wins. Your labels are a second opinion: the report and `calibrate`
show how often each limit agreed with your eye and the value that would agree better, and apply nothing;
if you accept one, the agent writes it to `limits.yaml` and notes that it came from you.

**Parameter check.** Runware runs and bills a request that carries a field it does not know, at the model's
default. So before `estimate` and `run`, one request per recipe is validated against the model's published
schema. A field the model does not have (`widht`, with "did you mean `width`?"), a value outside the allowed
set or range: the run stops before anything is paid. A field the schema calls required, or a rule between
fields, is printed and does not stop the run, because the published schemas are sometimes stricter than the
API. `--skip-model-check` turns it off. It cannot see rules the API enforces and the schema does not state.

**Models that change.** The same model id can change between two runs: status, price, a field, a default.
Each run keeps what Runware publishes about every model in `models.json` and stamps each result with it.
The next run prints what differs before spending (`status preview → live`, `price output: $0.0154 →
$0.01926`, `field added: ...`). Cached results from before a change are kept and marked in the report;
`run --regenerate-changed` makes them again. A model whose weights change while its schema, status and
price stay the same is not seen.

**Your own model.** A recipe can call an endpoint of a Runware Serverless app (`taskType: serverlessEndpoint`),
so a model you trained or deployed is benchmarked next to the catalogue's, with the same checks and its cost
per output worked out from GPU seconds. It was used to put a LoRA trained on Serverless back into the bench
that picked its teacher. The training side of that run (the app, its client, the dataset builder) is not in
this repository: the tool is about evaluation, and training is out of its scope.

**Spend.** `budget.maxSpend` (USD for one full run) is required. A run stops before it starts if the estimate passes the cap,
and holds the cap while running: each task starts only if what is spent, what is in flight and its
own estimate still fit, and a recipe that costs more than estimated is reserved at its real cost from
then on. Tasks that did not start are listed in the report; raise the cap and run again to fill them
in. A recipe with no known price must state one (`price:` in its file, USD per output).

**Interrupted runs.** Tasks are sent with Runware's async delivery and polled, so no connection is held open while a model works. Every task is logged in `submitted.jsonl` before it is sent. Run the same command
again and the runner first asks Runware for the results of tasks already sent; one that is still
running is not sent a second time.

**Model Router.** A recipe with `model: auto` lets [Runware's Model Router](https://runware.ai/model-router)
pick the model, among the bench's models (`routing.allowedModels: bench`) or the whole catalog, with your
weights and price ceiling. The router chooses from the request and never sees the output; the bench
measures what it produced. The report shows what it picked on each call, how those outputs did against
your checks, and how the same model did when called by name: use `auto` where its pick passes, and call a
model by name where it does not.

Recipes are one file each in `recipes/`, fingerprinted. Copy a file into another bench to share it;
matching past results (same fingerprint, same images, same draw) are reused instead of paid for:

```
uv run --project runner runware-eval recipes list    bench.yaml   # id, fingerprint, past runs
uv run --project runner runware-eval recipes extract bench.yaml   # move inline recipes into files
```

Without cloning: `uvx --from "git+https://github.com/risunobushi/runware-eval#subdirectory=runner" runware-eval …`

The runner is pinned to Python 3.12 (`runner/.python-version`) and to exact dependency versions
(`runner/uv.lock`, which covers Windows, macOS and Linux), so every machine gets the same environment
and the same metric values. You don't need Python installed: uv downloads 3.12 if it's missing. The
first run builds the environment (about a minute); later runs reuse it. Results are cached per
task, so re-running only pays for what is new. Each run folder ends with a single `report.html`.

## License

MIT
