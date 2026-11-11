"""Styles for the HTML report and the labeling page, on Runware's brand tokens (runware.ai, Nov 2026):
dark ground, white type, green-to-yellow as light, Figtree for text, JetBrains Mono for ids and numbers.
Runware's heading face (Coxx) is not public, so headings use Figtree as runware.ai's own fallback does."""

FONTS = ("<link rel='preconnect' href='https://fonts.googleapis.com'><link rel='preconnect' "
         "href='https://fonts.gstatic.com' crossorigin><link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
         "family=Figtree:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap'>")

CSS = """
:root{--green:#afff9f;--green-mid:#90f77c;--green-deep:#345c2d;--yellow:#ffff7d;--yellow-mid:#eeee5a;
--yellow-deep:#58582c;--page:#1a1a1a;--deep:#080808;--surface:#1c1c1c;--card:#1c1c1c;--raised:#252525;
--ink:#f2f2f2;--ink2:#c9c9c9;--muted:#9a9a9a;--grid:#2e2e2e;--axis:#454545;--accent:var(--green);
--good:var(--green);--good-ink:var(--green);--crit:#db4d00;--crit-ink:#ff8a4c;--warn:var(--yellow-mid);
--zone:rgba(175,255,159,.06);--chip-good:rgba(175,255,159,.12);--chip-bad:rgba(219,77,0,.18);
--glow:radial-gradient(circle at 14% 92%,rgba(175,255,159,.16),transparent 36%);
--sans:Figtree,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Consolas,monospace;--r:7px;color-scheme:dark}
*{box-sizing:border-box}[hidden]{display:none!important}html{background:var(--page)}
body{margin:0;overflow-x:clip;background:var(--page);color:var(--ink);font:15px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 88px;display:grid;gap:64px}
h1,h2,h3{margin:0;text-wrap:balance;font-weight:500;letter-spacing:-.02em}
h1{font-size:clamp(34px,5.6vw,60px);line-height:1.04}h2{font-size:clamp(24px,3vw,32px);line-height:1.15}
h3{font-size:15px;font-weight:600;letter-spacing:0}p{margin:0;max-width:72ch}
.muted{color:var(--muted)}.ink2{color:var(--ink2)}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums;letter-spacing:0}
.kicker{font:500 12px/1.4 var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.kicker b{color:var(--green);font-weight:500}
.strip{font:12px/1.5 var(--mono);color:var(--muted);font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
section,header,.wrap>*,.split>*,.below>*,.side,.panel,details{min-width:0}
section{display:grid;grid-template-columns:minmax(0,1fr);gap:18px}
.sec-head{display:grid;gap:8px;padding-top:22px;border-top:1px solid var(--grid)}
.sec-head .num{font:500 .5em var(--mono);color:var(--green);vertical-align:.45em;margin-right:12px}
/* hero: deep ground, dot grid, green light from the top right */
.hero{position:relative;margin:0 calc(50% - 50vw);padding:56px max(16px,calc(50vw - 574px)) 44px;display:grid;gap:18px;overflow:hidden;
background:radial-gradient(ellipse at top right,rgba(175,255,159,.13),transparent 55%),
radial-gradient(ellipse at 85% 0%,rgba(255,255,125,.07),transparent 40%),var(--deep);border-bottom:1px solid var(--grid)}
.hero::before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.5;
background:radial-gradient(circle,rgba(251,251,251,.16) .7px,transparent .8px) 0 0/22px 22px;
-webkit-mask-image:linear-gradient(200deg,#000 0%,transparent 60%);mask-image:linear-gradient(200deg,#000 0%,transparent 60%)}
.hero>*{position:relative}.hero .goal{color:var(--ink2);font-size:17px}
.hero h1 em{font-style:normal;background:linear-gradient(90deg,var(--green),var(--yellow));-webkit-background-clip:text;
background-clip:text;color:transparent}
.hero h1 .sub{display:block;margin-top:.35em;font-size:.5em;line-height:1.25;letter-spacing:-.01em;color:var(--ink2)}
.meta{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;margin:6px 0 0;background:var(--grid);
border:1px solid var(--grid);border-radius:var(--r);overflow:hidden}
@media (min-width:1000px){.meta{grid-template-columns:repeat(8,minmax(0,1fr))}}
@media (max-width:520px){.meta{grid-template-columns:repeat(2,minmax(0,1fr))}}
.meta div{background:var(--surface);padding:11px 14px;display:grid;gap:3px;align-content:start}
.meta dt{font:500 10.5px/1.3 var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.meta dd{margin:0;font:500 15px/1.3 var(--mono);color:var(--ink);font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--grid);border-radius:var(--r);padding:20px;display:grid;gap:8px;
align-content:start}
.card.lit{background:var(--glow),var(--card);border-color:var(--green-deep)}
.card .big{font:500 clamp(36px,4.4vw,52px)/1 var(--sans);letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.card.lit .big{color:var(--green)}.card .lab{font-size:13px;color:var(--ink2)}
.card .strip{color:var(--ink2)}
.fold>summary{font-weight:500;color:var(--ink2)}.fold[open]>summary{margin-bottom:12px}
.notes{display:grid;gap:6px;margin:0;padding:0;list-style:none}
.notes li{background:var(--raised);border-left:2px solid var(--green);border-radius:0 var(--r) var(--r) 0;font-size:14px}
.notes li.warn{border-left-color:var(--yellow-mid)}.notes strong,.notes b{font-weight:600}
.notes details{background:none;border:0;border-radius:0;padding:0}.notes summary,.notes .lead{padding:9px 14px;font-weight:400}
.notes .more{padding:0 14px 11px 30px;color:var(--ink2);max-width:92ch}
.tablewrap{overflow-x:auto;border:1px solid var(--grid);border-radius:var(--r);background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:10px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:middle;white-space:nowrap}
th+th,td+td{border-left:1px solid var(--grid)}tbody tr:nth-child(even){background:rgba(255,255,255,.015)}
tbody tr:hover{background:var(--raised)}tr:last-child td{border-bottom:0}
th{font:500 11px/1.3 var(--mono);text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
th.grp{text-align:center;color:var(--ink2)}
.chip{white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:4px;border-radius:99px;
padding:2px 8px;font-size:11.5px}
.chip.ok{background:var(--chip-good);color:var(--good-ink)}.chip.bad{background:var(--chip-bad);color:var(--crit-ink)}
.chip.na{color:var(--muted);border:1px dashed var(--axis)}
.rank{font:500 13px var(--mono);color:var(--muted)}tr:first-child .rank{color:var(--green)}.rowname{font-weight:600}
.linkish{all:unset;cursor:pointer;font-weight:600}.linkish:hover{color:var(--green)}
.linkish:focus-visible{outline:2px solid var(--green);outline-offset:2px}
.chartwrap{overflow-x:auto;border-radius:var(--r)}
.chart{width:100%;min-width:960px;height:auto;background:var(--glow),var(--surface);border:1px solid var(--grid);
border-radius:var(--r)}
.chart .grid{stroke:var(--grid);stroke-width:1}.chart .axis{stroke:var(--axis);stroke-width:1}
.chart .gate{stroke:var(--yellow-mid);stroke-width:1;stroke-dasharray:4 4;opacity:.6}
.chart .zone{fill:rgba(175,255,159,.09)}.chart .zone-label{font:11px var(--mono);fill:var(--green);letter-spacing:.06em}
.chart .tick{font:11px var(--mono);fill:var(--muted)}.chart .axis-title{font-size:15px;font-weight:500;fill:var(--ink)}
.chart .dot{fill:var(--green);stroke:var(--surface);stroke-width:2}.chart .dot.fail{fill:var(--page);stroke:var(--muted);
stroke-width:1.5}.chart .hit{fill:transparent}
.chart .dot.out{fill:var(--crit-ink)}.chart .pt.out .lbl{fill:var(--crit-ink)}.chart .pt.in .lbl{fill:var(--green)}
.chart .lbl{font:11px var(--mono);fill:var(--ink2)}.chart .pt:hover .dot{r:7}.chart .pt:hover .lbl{fill:var(--ink)}
.tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--deep);font:12px/1.4 var(--mono);
padding:6px 9px;border-radius:5px;opacity:0;transition:opacity .1s;z-index:9;max-width:340px}
.split{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:12px;align-items:start}
.below{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;align-items:start}
.below .wide{grid-column:1/-1}.panel .ba{width:100%;max-width:440px;justify-self:center}
@media (max-width:860px){.split{grid-template-columns:1fr}}
.picker{display:flex;flex-wrap:wrap;gap:6px}
.picker button{font:12.5px var(--mono);padding:7px 11px;border-radius:var(--r);border:1px solid var(--grid);
background:var(--card);color:var(--ink2);cursor:pointer;display:inline-flex;gap:8px;align-items:center}
.picker button:hover{border-color:var(--axis);color:var(--ink)}
.picker button[aria-pressed="true"]{border-color:var(--green);color:var(--ink);background:rgba(175,255,159,.08)}
.picker button:focus-visible{outline:2px solid var(--green);outline-offset:2px}
.picker .n{font-size:11px;color:var(--muted)}
.ba{position:relative;border-radius:var(--r);overflow:hidden;border:1px solid var(--grid);background:var(--deep);
user-select:none;touch-action:none}
.ba:focus-visible{outline:2px solid var(--green);outline-offset:2px}
.ba img{display:block;width:100%;height:auto}.ba .after{position:absolute;inset:0;clip-path:inset(0 0 0 50%)}
.ba .after img{height:100%;object-fit:cover}
.ba .bar{position:absolute;top:0;bottom:0;left:50%;width:2px;margin-left:-1px;background:var(--green);
box-shadow:0 0 14px rgba(175,255,159,.6)}
.ba .knob{position:absolute;top:50%;left:50%;width:36px;height:36px;margin:-18px 0 0 -18px;border-radius:50%;
background:var(--green);box-shadow:0 0 0 4px rgba(175,255,159,.18);display:grid;place-items:center;font-size:14px;
color:var(--deep)}
.ba .tag{position:absolute;top:10px;font:11.5px var(--mono);background:rgba(8,8,8,.78);color:var(--ink);
padding:4px 8px;border-radius:5px;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ba .tag.l{left:10px}.ba .tag.r{right:10px}
.side{display:grid;gap:12px}
.panel{background:var(--card);border:1px solid var(--grid);border-radius:var(--r);padding:16px;display:grid;gap:10px}
#heat-panel{max-width:560px}
.textout{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.55 var(--mono);color:var(--ink);background:var(--deep);border:1px solid var(--grid);border-radius:5px;padding:12px;max-height:340px;overflow:auto}
.panel img{width:100%;height:auto;border-radius:5px;display:block}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}.pair figure{margin:0;display:grid;gap:4px}
figcaption{font:11.5px var(--mono);color:var(--muted)}
.legend-bar{height:8px;border-radius:4px;background:linear-gradient(90deg,#1f3a1b,#345c2d,#6fbf5f,#afff9f,#ffff7d)}
.legend-ticks{display:flex;justify-content:space-between;font:11px var(--mono);color:var(--muted)}
dl.kv{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px 10px;margin:0;font-size:13px;align-items:center}
dl.kv dt{color:var(--ink2)}dl.kv dd{margin:0;white-space:nowrap}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}
.gallery figure{margin:0;background:var(--card);border:1px solid var(--grid);border-radius:var(--r);overflow:hidden;
display:grid;cursor:pointer;transition:border-color .15s}
.gallery figure:hover{border-color:var(--green)}
.gallery img{width:100%;height:auto;display:block;background:var(--deep)}
.gallery figcaption{padding:9px 11px 11px;display:grid;gap:5px;color:var(--ink)}
.gallery .row1{display:flex;justify-content:space-between;gap:6px;align-items:center;font:500 12.5px var(--sans)}
.gallery .row1 span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gallery .strip{font-size:10.5px}
.clipbar{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;font:12.5px var(--mono);color:var(--ink2)}
.clipbar select,.clipbar button{font:12.5px var(--mono);padding:6px 10px;border-radius:var(--r);border:1px solid var(--grid);
background:var(--card);color:var(--ink);cursor:pointer;max-width:100%}
.clipbar button{min-width:64px}.clipbar input[type=range]{flex:1 1 200px;min-width:0;accent-color:var(--green)}
.clips{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,440px));gap:12px;justify-content:center}
.clips figure{margin:0;display:grid;gap:6px}
.clips video{width:100%;max-height:72vh;object-fit:contain;border-radius:var(--r);background:var(--deep);display:block}
.tcharts{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.tcharts figure{margin:0;display:grid;gap:5px}
.tcharts svg{width:100%;height:auto;background:var(--surface);border:1px solid var(--grid);border-radius:5px;display:block}
.tcharts .tl{fill:none;stroke:var(--axis);stroke-width:1.2}.tcharts .tl.cur{stroke:var(--green);stroke-width:2}
.tcharts .td{fill:var(--axis)}.tcharts .td.cur{fill:var(--green)}.tcharts .ax{stroke:var(--axis);stroke-width:1}
.tcharts .lim{stroke:var(--yellow-mid);stroke-width:1;stroke-dasharray:4 4;opacity:.75}
.tcharts text{font:10px var(--mono);fill:var(--muted)}.tcharts g:hover .tl{stroke:var(--ink)}
details{background:var(--card);border:1px solid var(--grid);border-radius:var(--r);padding:13px 16px}
summary{cursor:pointer;font-weight:600}summary:hover{color:var(--green)}
.cta{display:flex;flex-wrap:wrap;gap:14px 24px;align-items:center;justify-content:space-between;padding:28px;
border:1px solid var(--green-deep);border-radius:var(--r);
background:radial-gradient(ellipse at 100% 100%,rgba(255,255,125,.08),transparent 50%),var(--glow),var(--card)}
.cta h2{font-size:clamp(22px,2.6vw,28px)}
.cta code{font:13px var(--mono);background:var(--deep);border:1px solid var(--grid);border-radius:5px;padding:9px 12px;
color:var(--green);overflow-wrap:anywhere}
"""
