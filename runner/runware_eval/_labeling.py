"""Labeling inside the report: markup, styles and the page script.

The report is a static file, so everything here runs in the reader's browser: labels are kept in the
browser's local storage (per run), and agreement with the checks, suggested thresholds and the
pairwise ranking are computed in the page. `Export labels.json` writes the same format that
`runware-eval calibrate --labels` reads, for when the labels should reach the bench or a colleague.

The part of the script between CAL-BEGIN and CAL-END has no page dependencies and mirrors
calibrate.py; tests/test_labeling_js.py runs it in Node against the Python implementation.
"""
import hashlib
import itertools
import math
import random

CSS = """
.task{display:grid;gap:14px}.row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}
.row figure{margin:0;display:grid;gap:4px}.row img{width:100%;height:auto;max-height:58vh;object-fit:contain;background:var(--deep);border-radius:var(--r);border:1px solid var(--grid)}
.btns{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.btns button,.tabs button{font:inherit;font-size:14px;padding:8px 14px;
border-radius:var(--r);border:1px solid var(--grid);background:var(--card);color:var(--ink);cursor:pointer}
.btns button:hover,.tabs button:hover{border-color:var(--axis)}
.btns button.on{border-color:var(--green);background:rgba(175,255,159,.1);color:var(--green)}
.progress{font:12.5px var(--mono);color:var(--ink2)}.kbd{font-family:var(--mono);font-size:12px;
border:1px solid var(--grid);border-radius:4px;padding:0 5px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}.tabs button[aria-pressed=true]{border-color:var(--green);
background:rgba(175,255,159,.08)}.tabs .sp{margin-left:auto}
#lab-box>summary{cursor:pointer;font-weight:600}#lab-result{display:grid;gap:12px;margin-top:12px}
"""

JS = r"""
// CAL-BEGIN  (pure functions: no page access; mirrors calibrate.py)
const LOWER = ['max', 'mean_max', 'p95_max', 'max_px', 'aspect_tolerance', 'dL_max'], HIGHER = ['min', 'dL_min'];
function calDirection(t){
  if ('abs_max' in t) return ['abs_lower', 'abs_max'];
  for (const k of LOWER) if (k in t) return ['lower', k];
  for (const k of HIGHER) if (k in t) return ['higher', k];
  return [null, null];
}
function calValue(m, key){
  if (key === 'mean_max') return m.mean ?? m.v;
  if (key === 'p95_max') return m.p95 ?? m.v;
  return m.v;
}
function calBalanced(pred, good){
  let tp = 0, tn = 0, g = 0, b = 0;
  for (let i = 0; i < pred.length; i++){ if (good[i]) { g++; if (pred[i]) tp++; } else { b++; if (!pred[i]) tn++; } }
  return (tp / Math.max(1, g) + tn / Math.max(1, b)) / 2;
}
function calAuc(vals, good){
  const pos = vals.filter((_, i) => good[i]), neg = vals.filter((_, i) => !good[i]);
  if (!pos.length || !neg.length) return null;
  let wins = 0;
  for (const p of pos) for (const n of neg) wins += (p > n ? 1 : 0) + (p === n ? 0.5 : 0);
  return wins / (pos.length * neg.length);
}
function calBradleyTerry(pairs, fileRecipe, iters = 200){
  const recs = [...new Set(Object.values(fileRecipe))].sort(), idx = {};
  recs.forEach((r, i) => idx[r] = i);
  const n = recs.length, w = recs.map(() => new Array(n).fill(0));
  for (const p of pairs){
    const a = fileRecipe[p.a], b = fileRecipe[p.b];
    if (a === undefined || b === undefined || a === b) continue;
    const i = idx[a], j = idx[b];
    if (p.winner === 'a') w[i][j] += 1; else if (p.winner === 'b') w[j][i] += 1; else { w[i][j] += .5; w[j][i] += .5; }
  }
  const games = (i, j) => w[i][j] + w[j][i];
  let s = new Array(n).fill(1);
  for (let it = 0; it < iters; it++){
    const next = s.map((_, i) => {
      let wins = .5, denom = 1 / (s[i] + 1);  // one virtual draw against an average opponent
      for (let j = 0; j < n; j++){ wins += w[i][j]; if (games(i, j)) denom += games(i, j) / (s[i] + s[j]); }
      return wins / denom;
    });
    const gm = Math.exp(next.reduce((a, x) => a + Math.log(x), 0) / n);
    s = next.map(x => x / gm);
  }
  const out = {};
  recs.forEach((r, i) => {
    let g = 0, wn = 0;
    for (let j = 0; j < n; j++){ g += games(i, j); wn += w[i][j]; }
    if (g) out[r] = {score: s[i], wins: wn, games: g};
  });
  return out;
}
function calibrate(cal, labels, pairs){
  // cal: {file: {recipe, m: [{d, l, g, p, v, mean, p95, t}]}}; labels: {file: 'good' | 'bad'}
  const lab = {};
  for (const [f, v] of Object.entries(labels)) if (cal[f]) lab[f] = v === 'good';
  const files = Object.keys(lab);
  const out = {labeled: files.length, good: files.filter(f => lab[f]).length, gates: [], ranks: [], human_ranking: {}};
  const rows = {};
  for (const f of files) for (const m of cal[f].m){
    const key = m.d + '\u0001' + m.l + '\u0001' + (m.g ? 'gate' : 'rank');
    (rows[key] = rows[key] || []).push([m, lab[f]]);
  }
  for (const key of Object.keys(rows).sort()){
    const [dim, lbl, mode] = key.split('\u0001'), xs = rows[key], good = xs.map(x => x[1]);
    if (mode === 'gate'){
      const t0 = xs[0][0].t || {}, [dir, k] = calDirection(t0), passes = xs.map(x => x[0].p);
      if (dir === null || passes.some(p => p === null || p === undefined)) continue;
      let vals = xs.map(x => calValue(x[0], k));
      if (dir === 'abs_lower') vals = vals.map(Math.abs);
      const now = calBalanced(passes, good);
      let best = [now, t0[k]];
      const cand = [...new Set(vals.filter(v => v !== null && v !== undefined && !Number.isNaN(v)))].sort((a, b) => a - b);
      for (let i = 0; i + 1 < cand.length; i++){
        const t = (cand[i] + cand[i + 1]) / 2;
        const score = calBalanced(vals.map(v => dir === 'higher' ? v >= t : v <= t), good);
        if (score > best[0] + 1e-9) best = [score, Math.round(t * 1e4) / 1e4];
      }
      out.gates.push({dimension: dim, label: lbl, key: k, n: xs.length, threshold_now: t0[k], agreement_now: now,
                      suggested: best[1], agreement_suggested: best[0]});
    } else {
      const ok = xs.filter(x => x[0].v !== null && x[0].v !== undefined && !Number.isNaN(x[0].v));
      const a = ok.length ? calAuc(ok.map(x => x[0].v), ok.map(x => x[1])) : null;
      if (a !== null) out.ranks.push({dimension: dim, label: lbl, n: ok.length, auc: a});
    }
  }
  const fileRecipe = {};
  for (const [f, c] of Object.entries(cal)) fileRecipe[f] = c.recipe;
  if (pairs && pairs.length) out.human_ranking = calBradleyTerry(pairs, fileRecipe);
  out.few_labels = out.labeled < 20 || Math.min(out.good, out.labeled - out.good) < 5;
  return out;
}
// CAL-END

(function(){
  const L = D.lab;
  if (!L) return;
  const $ = id => document.getElementById(id), KEY = 'runware-eval:labels:' + L.run_id;
  const S = {labels: {}, pairs: {}, i: 0, j: 0, tab: 'label', hot: false};
  const pk = p => p.a + '|' + p.b;
  function take(obj){  // labels.json shape -> state
    Object.assign(S.labels, obj.labels || {});
    for (const p of obj.pairs || []) S.pairs[pk(p)] = p;
  }
  take(L.initial || {});
  try { take(JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (err) {}
  const dump = () => ({bench: L.bench, run: L.run, labels: S.labels, pairs: Object.values(S.pairs)});
  function save(){ try { localStorage.setItem(KEY, JSON.stringify(dump())); } catch (err) {} results(); }
  const f = v => v === null || v === undefined || Number.isNaN(v) ? '—' : Math.abs(v) < 1 ? v.toFixed(3) : Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1);
  const pct = v => Math.round(v * 100) + '%';
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  function render(){
    for (const t of ['label', 'pair']) $('t-' + t).hidden = S.tab !== t;
    document.querySelectorAll('#lab-box .tabs button[data-tab]').forEach(b => b.setAttribute('aria-pressed', b.dataset.tab === S.tab));
    const it = L.items[S.i];
    $('l-orig').src = D.originals[it.input].img; $('l-out').src = D.items[it.key].img;
    $('l-prog').textContent = `Output ${S.i + 1} of ${L.items.length} · labeled ${L.items.filter(x => S.labels[x.file]).length}`;
    document.querySelectorAll('[data-lab]').forEach(b => b.classList.toggle('on', S.labels[it.file] === b.dataset.lab));
    if (L.pairs.length){
      const p = L.pairs[S.j], cur = S.pairs[pk(p)];
      $('p-orig').src = D.originals[p.input].img; $('p-a').src = D.items[p.ka].img; $('p-b').src = D.items[p.kb].img;
      $('p-prog').textContent = `Pair ${S.j + 1} of ${L.pairs.length} · answered ${L.pairs.filter(x => S.pairs[pk(x)]).length}`;
      document.querySelectorAll('[data-win]').forEach(b => b.classList.toggle('on', !!cur && cur.winner === b.dataset.win));
    }
  }
  function lab(v){ S.labels[L.items[S.i].file] = v; if (S.i < L.items.length - 1) S.i++; save(); render(); }
  function win(v){ const p = L.pairs[S.j]; S.pairs[pk(p)] = {a: p.a, b: p.b, winner: v}; if (S.j < L.pairs.length - 1) S.j++; save(); render(); }

  function results(){
    const nl = Object.keys(S.labels).length, np = Object.keys(S.pairs).length;
    $('lab-count').textContent = nl || np ? `${nl} labeled, ${np} pairs answered` : 'optional';
    const c = calibrate(D.cal, S.labels, Object.values(S.pairs)), box = $('lab-result');
    let h = '';
    if (c.labeled || np){
      h += `<p class="ink2">Your preference, set against this brief's thresholds: it informs your choice and changes nothing for other users. `
         + `${c.labeled} outputs labeled (${c.good} good). Balanced agreement: 50% = chance. `
         + (c.few_labels ? 'Few labels (about 20, with at least 5 good and 5 bad, make suggestions dependable): treat them as hints. ' : '')
         + `Suggestions are not applied to <span class="mono">bench.yaml</span>.</p>`;
    }
    if (c.gates.length){
      h += '<div class="tablewrap"><table><thead><tr><th>Check</th><th>Threshold</th><th>Agrees with you</th><th>Suggested</th><th>Would agree</th></tr></thead><tbody>'
        + c.gates.map(g => `<tr><td>${esc(g.label)}</td><td class="mono">${esc(g.key)}: ${f(g.threshold_now)}</td><td class="mono">${pct(g.agreement_now)}</td>`
            + `<td class="mono">${g.suggested !== g.threshold_now ? f(g.suggested) : '—'}</td><td class="mono">${pct(g.agreement_suggested)}</td></tr>`).join('')
        + '</tbody></table></div>';
    }
    if (c.ranks.length){
      h += '<div class="tablewrap"><table><thead><tr><th>Rank metric</th><th>Orders your good above your bad (AUC)</th></tr></thead><tbody>'
        + c.ranks.map(r => `<tr><td>${esc(r.label)}</td><td class="mono">${r.auc.toFixed(2)}${r.auc < .7 ? ' · weak' : ''}</td></tr>`).join('') + '</tbody></table></div>';
    }
    const hr = Object.entries(c.human_ranking).sort((a, b) => b[1].score - a[1].score);
    if (hr.length){
      h += '<h3>Your ranking</h3><div class="tablewrap"><table><thead><tr><th>#</th><th>Recipe</th><th>Score (1.0 = average)</th><th>Wins</th></tr></thead><tbody>'
        + hr.map(([r, v], i) => `<tr><td class="rank">${i + 1}</td><td>${esc(r)}</td><td class="mono">${v.score.toFixed(2)}</td><td class="mono">${+v.wins.toFixed(1)} / ${+v.games.toFixed(1)}</td></tr>`).join('')
        + '</tbody></table></div>';
    }
    box.innerHTML = h;
    // "Your pick" beside the verdict
    const line = $('pick-line'), card = $('pick-card'), top = hr.find(([r]) => D.recipes[r]);
    line.hidden = card.hidden = !top;
    if (!top) return;
    const [pick, pv] = top, pa = D.recipes[pick], wins = `${+pv.wins.toFixed(1)} of ${+pv.games.toFixed(1)} blind comparisons won`;
    const verdict = pick === D.best ? 'the same recipe the checks favour'
      : `passes ${pa.checks - pa.fails} of ${pa.checks} checks${pa.cost !== null ? ', $' + pa.cost.toFixed(3) + ' per output' : ''}. `
        + `Your eye and this brief's checks disagree: read the measurements below before choosing`;
    line.innerHTML = `<strong>Your pick: ${esc(pick)}</strong> (${wins}), ${verdict}. Your labels are your preference, not a threshold for anyone else.`;
    $('pick-big').textContent = `${+pv.wins.toFixed(1)}/${+pv.games.toFixed(1)} won`;
    $('pick-foot').textContent = `${pick} · ${pa.model}`;
  }

  document.querySelectorAll('[data-lab]').forEach(b => b.onclick = () => lab(b.dataset.lab));
  document.querySelectorAll('[data-win]').forEach(b => b.onclick = () => win(b.dataset.win));
  document.querySelectorAll('[data-nav]').forEach(b => b.onclick = () => {
    const d = +b.dataset.nav;
    if (S.tab === 'label') S.i = Math.max(0, Math.min(L.items.length - 1, S.i + d));
    else S.j = Math.max(0, Math.min(L.pairs.length - 1, S.j + d));
    render(); });
  document.querySelectorAll('#lab-box .tabs button[data-tab]').forEach(b => b.onclick = () => { S.tab = b.dataset.tab; render(); });
  const boxEl = $('lab-box');
  boxEl.addEventListener('mouseenter', () => S.hot = true); boxEl.addEventListener('mouseleave', () => S.hot = false);
  document.addEventListener('keydown', ev => {
    if (!S.hot || !boxEl.open || ev.target.tagName === 'INPUT') return;
    if (S.tab === 'label') { if (ev.key === 'g') lab('good'); if (ev.key === 'b') lab('bad'); }
    else if (['ArrowLeft', 'ArrowRight', 'ArrowDown'].includes(ev.key)) {
      ev.preventDefault(); win(ev.key === 'ArrowLeft' ? 'a' : ev.key === 'ArrowRight' ? 'b' : 'tie'); }
  });
  $('lab-export').onclick = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(dump(), null, 1)], {type: 'application/json'}));
    a.download = 'labels.json'; a.click();
  };
  $('lab-import').onchange = ev => {
    const file = ev.target.files[0]; if (!file) return;
    file.text().then(t => { try { take(JSON.parse(t)); save(); render(); } catch (err) { $('lab-count').textContent = 'that file is not a labels.json'; } });
    ev.target.value = '';
  };
  $('lab-clear').onclick = () => {
    if ($('lab-clear').dataset.sure !== '1') { $('lab-clear').dataset.sure = '1'; $('lab-clear').textContent = 'Click again to clear'; return; }
    S.labels = {}; S.pairs = {}; S.i = S.j = 0; $('lab-clear').dataset.sure = ''; $('lab-clear').textContent = 'Clear';
    try { localStorage.removeItem(KEY); } catch (err) {}
    results(); render();
  };
  render(); results();
})();
"""


def _finite(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def data(scored, items, title, run_name, initial=None, pairs_per_recipe=4, seed=7):
    """What the page needs: check values for every scored output (`cal`), and the outputs and pairs to
    show, shuffled once here so the order is the same every time the report is opened."""
    cal = {}
    for s in scored:
        ms = []
        for m in s["metrics"]:
            if m.get("status") != "ok":
                continue
            v = m.get("values") or {}
            ms.append({"d": m["dimension"], "l": m["label"], "g": m["mode"] == "gate", "p": m.get("pass"),
                       "v": _finite(v.get("value")), "mean": _finite(v.get("mean")), "p95": _finite(v.get("p95")),
                       "t": {k: x for k, x in (m.get("thresholds") or {}).items() if _finite(x) is not None}})
        cal[s["file"]] = {"recipe": s["recipe"], "m": ms}
    rng = random.Random(seed)
    shown = [{"file": it["file"], "key": key, "input": it["input"], "recipe": it["recipe"]} for key, it in items.items()]
    rng.shuffle(shown)
    by_input = {}
    for x in sorted(shown, key=lambda x: x["file"]):
        by_input.setdefault(x["input"], []).append(x)
    pool = [(x, y) for xs in by_input.values() for x, y in itertools.combinations(xs, 2) if x["recipe"] != y["recipe"]]
    rng.shuffle(pool)
    want = pairs_per_recipe * len({x["recipe"] for x in shown}) // 2 or 1
    pairs = []
    for x, y in pool[:want]:
        a, c = (x, y) if rng.random() < 0.5 else (y, x)
        pairs.append({"a": a["file"], "b": c["file"], "ka": a["key"], "kb": c["key"], "input": a["input"]})
    run_id = hashlib.sha1(("|".join(sorted(cal)) + "|" + title).encode()).hexdigest()[:12]
    return cal, {"bench": title, "run": run_name, "run_id": run_id, "initial": initial or {},
                 "items": [{k: x[k] for k in ("file", "key", "input")} for x in shown], "pairs": pairs}


def section(n_pairs):
    return (
        "<details id='lab-box'><summary>Label the outputs yourself (<span id='lab-count'>optional</span>)</summary>"
        "<p class='ink2'>Mark outputs good or bad, then pick the better of two. Recipe names are hidden here and "
        "the order is shuffled. Each recipe is shown at its best seed (the one that fails the fewest checks). "
        "Labels are kept in this browser, for this report; export them to share them or to "
        "use them with <span class='mono'>runware-eval calibrate</span>.</p>"
        "<div class='tabs'><button data-tab='label'>1 · Good or bad</button>"
        f"<button data-tab='pair'>2 · Which is better ({n_pairs} pairs)</button><span class='sp'></span>"
        "<button id='lab-export'>Export labels.json</button>"
        "<label class='linkish' style='align-self:center;cursor:pointer'>Import<input id='lab-import' type='file' "
        "accept='.json,application/json' hidden></label><button id='lab-clear'>Clear</button></div>"
        "<div id='t-label' class='task'><div class='row'><figure><img id='l-orig' alt='Original'>"
        "<figcaption>original</figcaption></figure><figure><img id='l-out' alt='Output'>"
        "<figcaption>output</figcaption></figure></div><div class='btns'>"
        "<button data-lab='good'>Good <span class='kbd'>g</span></button>"
        "<button data-lab='bad'>Bad <span class='kbd'>b</span></button>"
        "<button data-nav='-1'>← back</button><button data-nav='1'>skip →</button>"
        "<span class='progress' id='l-prog'></span></div></div>"
        "<div id='t-pair' class='task' hidden><figure style='margin:0;max-width:300px'><img id='p-orig' "
        "alt='Original' style='width:100%;border-radius:var(--r)'><figcaption>original</figcaption></figure>"
        "<div class='row'><figure><img id='p-a' alt='Option A'><figcaption>A</figcaption></figure>"
        "<figure><img id='p-b' alt='Option B'><figcaption>B</figcaption></figure></div><div class='btns'>"
        "<button data-win='a'>A is better <span class='kbd'>←</span></button>"
        "<button data-win='b'>B is better <span class='kbd'>→</span></button>"
        "<button data-win='tie'>About the same <span class='kbd'>↓</span></button>"
        "<button data-nav='-1'>← back</button><button data-nav='1'>skip →</button>"
        "<span class='progress' id='p-prog'></span></div></div></details><div id='lab-result'></div>")
