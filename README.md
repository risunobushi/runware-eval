# runware-eval

A test bench for [Runware](https://runware.ai) models. Tell your agent what you're making and what
"good" means for you. It finds the Runware models and settings that can do the job, picks the
metrics that measure your definition of good, and writes a `bench.yaml` you can re-run whenever a
new model ships.

> Status: the skill sets up the bench; the runner (`runner/`) estimates, runs, scores and reports it,
> with pixel checks, a panel of vision-model judges, blind human labeling and calibration. OCR checks
> are planned and show as *not run* in reports. Tested on Windows; macOS and Linux are untested.

## Install

**Claude Code** (plugin):

```
/plugin marketplace add risunobushi/runware-eval
/plugin install eval@runware-eval
```

**Any other agent with a shell:** copy `skills/runware-eval/` to where your agent loads skills
(`.claude/skills/`, `.cursor/skills/`, `.agents/skills/`).

The skill sets up the two tools it needs on first use, with no admin rights and no restart: the
[Runware CLI](https://github.com/runware/runware-cli) (catalog, uploads, and the one sign-in:
`runware auth login`) and [uv](https://docs.astral.sh/uv/) (runs the bench runner in its own
environment). No MCP server is needed.

## Use

Ask your agent something like *"Which Runware model is best for adding a contact shadow without
changing my product?"* The skill will:

1. check the Runware CLI and uv, install what is missing, and ask you to sign in once;
2. ask what you want to evaluate (deviation, pixel shift, identity, text, prompt adherence,
   aesthetics, technical quality), with cost and latency always measured;
3. pick metrics from the library (`references/metric-catalog.md`), or write a new one with you;
4. find candidate models in the catalog with the CLI and read their schemas;
5. write `bench.yaml` and one file per recipe, and estimate the cost;
6. run a smoke round, then the full run, and hand you a single HTML report.

## Runner

Runs through [uv](https://docs.astral.sh/uv/), so nothing is installed into your Python and no admin
rights are needed. Needs the Runware CLI signed in (`runware auth login`).

```
uv run --project runner runware-eval estimate bench.yaml --round smoke
uv run --project runner runware-eval run      bench.yaml --round smoke   # first input, first seed
uv run --project runner runware-eval run      bench.yaml --round full    # stops before passing the budget
uv run --project runner runware-eval report   bench.yaml --round full --notes notes.json
uv run --project runner runware-eval label     bench.yaml --round full    # blind good/bad and pairwise page
uv run --project runner runware-eval calibrate bench.yaml --round full --labels labels.json
```

The report leads with the best recipe: fewest failed checks, then lowest cost. It names the checks
that recipe still misses, so "best" never hides a failure.

**Spend.** `budget.max_usd` is required. A run stops before it starts if the estimate passes the cap,
and holds the cap while running: each task starts only if what is spent, what is in flight and its
own estimate still fit, and a recipe that costs more than estimated is reserved at its real cost from
then on. Tasks that did not start are listed in the report; raise the cap and run again to fill them
in. A recipe with no known price must state one (`price_usd:` in its file).

**Interrupted runs.** Tasks are sent with Runware's async delivery and polled, so no connection is held open while a model works. Every task is logged in `submitted.jsonl` before it is sent. Run the same command
again and the runner first asks Runware for the results of tasks already sent; one that is still
running is not sent a second time.

Recipes are one file each in `recipes/`, fingerprinted. Copy a file into another bench to share it;
matching past results (same fingerprint, same images, same seed) are reused instead of paid for:

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
