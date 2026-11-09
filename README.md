# runware-eval

A test bench for [Runware](https://runware.ai) models. Tell your agent what you're making and what
"good" means for you. It finds the Runware models and settings that can do the job, picks the
metrics that measure your definition of good, and writes a `bench.yaml` you can re-run whenever a
new model ships.

> Status: the skill sets up the bench; the runner (`runner/`) estimates, runs, scores and reports it.
> Vision-model judges, OCR and human ranking are planned and show as *not run* in reports.

## Install

**Claude Code** (plugin, includes the Runware MCP):

```
/plugin marketplace add risunobushi/runware-eval
/plugin install eval@runware-eval
```

**Any other agent:** copy `skills/runware-eval/` to where your agent loads skills
(`.claude/skills/`, `.cursor/skills/`, `.agents/skills/`), then connect the Runware MCP:

```
claude mcp add --transport http runware https://mcp.runware.ai
```

## Use

Ask your agent something like *"Which Runware model is best for adding a contact shadow without
changing my product?"* The skill will:

1. check that the Runware MCP is connected, and help you install it if not;
2. ask what you want to evaluate (deviation, pixel shift, identity, text, prompt adherence,
   aesthetics, technical quality), with cost and latency always measured;
3. pick metrics for those dimensions from `references/metrics.md`;
4. find candidate models through the MCP and read their schemas;
5. write `bench.yaml` (format in `references/bench-format.md`) and estimate the cost;
6. run a one-input smoke round before anything bigger.

## Runner

```
pip install --no-deps -e runner            # needs the Runware CLI signed in (`runware auth login`)
python -m runware_eval estimate bench.yaml --round smoke
python -m runware_eval run      bench.yaml --round smoke      # first input, first seed, every recipe
python -m runware_eval run      bench.yaml --round full       # everything, stops before passing the budget
python -m runware_eval report   bench.yaml --round full --notes notes.json
```

`python -m runware_eval` works without admin rights; the `runware-eval` shortcut needs write
access to Python's `Scripts` folder. Results are cached per task, so re-running only pays for what is new. Each run folder ends with a
single `report.html`.

## License

MIT
