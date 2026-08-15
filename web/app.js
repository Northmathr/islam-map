/* Islam in Britain — census map.
 *
 * The tool covers three subjects that differ on every axis that matters:
 *
 *   people      census      district areas   decennial    near-complete
 *   provision   mosques     points           no series    undercounts, unevenly
 *   activity    planning    points           continuous   flaky feed, fuzzy text
 *
 * So they are not alternatives in one metric list — putting "Muslims per mosque"
 * next to "Median age" is a category error, not just clutter. Instead each
 * subject is a LENS that reconfigures the metric list, the open filter group,
 * the time axis and the default panel tab. Control count stays flat.
 *
 * Point data (mosques, applications) are OVERLAYS available in every lens
 * rather than being locked to one, because mosque points over the demographic
 * choropleth is the most useful view in the product and a lens-exclusive design
 * would make it impossible.
 *
 * Selection and filters persist across lenses. That persistence is what makes
 * this one tool rather than three.
 *
 * Provision and Activity ship visible but empty until Phase 2/3 ingestion lands;
 * their empty states name the source that will fill them.
 */

const DOT_PEOPLE = 150;
const PREV = "2011", NOW = "2021";

const state = {
  lens: "people",
  metric: "sr",
  mode: "choropleth",
  period: NOW,
  basis: "sr",
  window: 24,                 // months, activity lens
  overlays: { mosques: false, applications: false },
  selected: null,
  tab: "dem",
  filters: {},
  transform: d3.zoomIdentity,
};

let DATA, GEO, POINTS, path, projection;
let svg, gMap, canvas, ctx, colorScale;

const $ = id => document.getElementById(id);
const fmt = d3.format(",");
const fmt1 = d3.format(".1f");
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

/* ---------------- lenses ---------------- */

const METRICS = {
  // people
  sr:   { lens: "people", label: "Muslim share of respondents", unit: "%", basis: true, prev: "sr11", dp: 1 },
  c:    { lens: "people", label: "Muslim population", unit: "", prev: "c11", dp: 0 },
  k:    { lens: "people", label: "Muslims per 10,000 respondents", unit: "", dp: 0 },
  dpp:  { lens: "people", label: "Change since 2011 (percentage points)", unit: "pp", diverging: true, dp: 1 },
  drel: { lens: "people", label: "Change since 2011 (relative)", unit: "%", diverging: true, dp: 0 },
  med:  { lens: "people", label: "Median age (Muslim)", unit: "", dp: 1 },
  u16:  { lens: "people", label: "Under 16 (Muslim)", unit: "%", dp: 1 },
  ukb:  { lens: "people", label: "UK-born (Muslim)", unit: "%", dp: 1 },
  nrp:  { lens: "people", label: "Religion question not answered", unit: "%", dp: 1 },
  pop:  { lens: "people", label: "Total population", unit: "", prev: "p11", dp: 0 },

  // provision — Phase 2
  mq:   { lens: "provision", label: "Mosques", unit: "", dp: 0, pending: true },
  ratio:{ lens: "provision", label: "Muslims per mosque", unit: "", dp: 0, pending: true },
  mq100:{ lens: "provision", label: "Mosques per 100,000 Muslims", unit: "", dp: 1, pending: true },

  // activity — Phase 3
  apps: { lens: "activity", label: "Planning applications in window", unit: "", dp: 0, pending: true },
  appr: { lens: "activity", label: "Approved in window", unit: "", dp: 0, pending: true },
  net:  { lens: "activity", label: "Net change from planning outcomes", unit: "", diverging: true, dp: 0, pending: true },
};

const LENSES = [
  { id: "people",    label: "People",    tab: "dem", time: "census",
    blurb: "Census demography — who lives where, and how it changed." },
  { id: "provision", label: "Provision", tab: "pro", time: "census",
    blurb: "Mosques and worshippers per mosque, mapped as service capacity.",
    empty: {
      title: "Provision data not ingested yet",
      body: `Phase 2 fills this from the certified places of worship register
             (official, undercounts), the Charity Commission register, OpenStreetMap
             and community mosque directories — shown as a range across source tiers
             rather than a single number, because the tiers disagree substantially.`,
    } },
  { id: "activity",  label: "Activity",  tab: "act", time: "window",
    blurb: "Planning applications concerning mosques, all outcomes, over time.",
    empty: {
      title: "Planning data not ingested yet",
      body: `Phase 3 fills this from PlanIt and planning.data.gov.uk, filtered on
             use class F1(f) (D1 pre-2020 and in Wales) plus text classification.
             Ingested to local snapshots on a schedule — the map never fetches the
             feed live, because it is not reliable enough to sit in the render path.`,
    } },
];

const lens = () => LENSES.find(l => l.id === state.lens);
const lensPending = () => METRICS[state.metric]?.pending;

const FILTER_GROUPS = [
  { lens: "people", label: "People", filters: [
    { key: "pop", label: "Total population", dp: 0 },
    { key: "c",   label: "Muslim population", dp: 0 },
    { key: "sr",  label: "Share of respondents", unit: "%", dp: 1 },
    { key: "dpp", label: "Change since 2011", unit: "pp", dp: 1 },
    { key: "med", label: "Median age", dp: 1 },
    { key: "ukb", label: "UK-born", unit: "%", dp: 1 },
    { key: "nrp", label: "Not answered", unit: "%", dp: 1 },
  ]},
  { lens: "provision", label: "Provision", pending: true, filters: [
    { key: "mq",    label: "Mosques", dp: 0 },
    { key: "ratio", label: "Muslims per mosque", dp: 0 },
  ]},
  { lens: "activity", label: "Activity", pending: true, filters: [
    { key: "apps", label: "Applications in window", dp: 0 },
  ]},
];

const ALL_FILTERS = FILTER_GROUPS.filter(g => !g.pending).flatMap(g => g.filters);

const OVERLAYS = [
  { id: "mosques", label: "Mosques", pending: true,
    note: "Mosque locations — Phase 2. Available in every lens, so provision can be read against demography." },
  { id: "applications", label: "Applications", pending: true,
    note: "Planning applications — Phase 3. Marker layer, never blended into the choropleth." },
];

const FAITH_COLORS = {
  "Muslim": "#37c8c3", "Christian": "#5b7fa6", "No religion": "#3e4a5a",
  "Hindu": "#c9803f", "Sikh": "#8a6fb0", "Jewish": "#a8b04f",
  "Buddhist": "#4f9e7a", "Other religion": "#6d7482", "Not answered": "#2a323d",
};

function value(d, key = state.metric) {
  const m = METRICS[key];
  if (!m || m.pending) return null;
  if (state.period === PREV && lens().time === "census") {
    if (!m.prev) return null;
    return d[m.prev];
  }
  if (m.basis) return d[state.basis];
  return d[key];
}

function metricLabel() {
  const m = METRICS[state.metric];
  if (state.metric === "sr" && state.basis === "sa") return "Muslim share of all residents";
  return m.label;
}

/* ---------------- boot ---------------- */

Promise.all([
  d3.json("data/districts.json"),
  d3.json("data/lad_boundaries.json"),
  d3.json("data/lsoa_points.json"),
]).then(([data, geo, points]) => {
  DATA = data;
  POINTS = points;
  GEO = { type: "FeatureCollection",
          features: geo.features.filter(f => DATA.districts[f.properties.LAD24CD]) };
  init();
});

function init() {
  buildLensBar();
  buildOverlays();
  setupMap();      // before buildSliders: its sync() calls render(), which needs the svg
  buildSliders();
  wireControls();
  applyLens(state.lens, true);
}

/* ---------------- lens + overlay chrome ---------------- */

function buildLensBar() {
  $("lens").innerHTML = LENSES.map(l =>
    `<button data-lens="${l.id}" class="${l.id === state.lens ? "on" : ""}"
      title="${esc(l.blurb)}">${esc(l.label)}${l.empty ? '<i class="dot"></i>' : ""}</button>`
  ).join("");
  d3.selectAll("#lens button").on("click", function () { applyLens(this.dataset.lens); });
}

function buildOverlays() {
  $("overlays").innerHTML = OVERLAYS.map(o =>
    `<button class="chip ${o.pending ? "pending" : ""}" data-ov="${o.id}"
      ${o.pending ? "disabled" : ""} title="${esc(o.note)}">
      <i class="sw"></i>${esc(o.label)}${o.pending ? '<em>soon</em>' : ""}</button>`
  ).join("");
  d3.selectAll("#overlays button:not([disabled])").on("click", function () {
    const id = this.dataset.ov;
    state.overlays[id] = !state.overlays[id];
    d3.select(this).classed("on", state.overlays[id]);
    render();
  });
}

function applyLens(id, first) {
  state.lens = id;
  d3.selectAll("#lens button").classed("on", function () { return this.dataset.lens === id; });

  // metric list is lens-scoped
  const opts = Object.entries(METRICS).filter(([, m]) => m.lens === id);
  $("metric").innerHTML = opts.map(([k, m]) =>
    `<option value="${k}">${esc(m.label)}</option>`).join("");
  if (!METRICS[state.metric] || METRICS[state.metric].lens !== id) state.metric = opts[0][0];
  $("metric").value = state.metric;

  // open this lens's filter group, collapse the others
  d3.selectAll("#sliders .group").classed("open", function () {
    return this.dataset.group === id;
  });

  state.tab = lens().tab;
  if (!first) { /* selection persists deliberately */ }

  buildTimeAxis();
  render();
  renderPanel();
}

/* ---------------- filter rail ---------------- */

function extent(key) {
  const vals = Object.values(DATA.districts).map(d => d[key]).filter(v => v != null);
  return [d3.min(vals), d3.max(vals)];
}

function buildSliders() {
  const host = $("sliders");
  host.innerHTML = "";

  // Seed every range first. Building a slider calls sync() -> render() -> passes(),
  // which reads all of them, so they must all exist before the first one renders.
  const ranges = {};
  ALL_FILTERS.forEach(f => { ranges[f.key] = extent(f.key); state.filters[f.key] = ranges[f.key]; });

  FILTER_GROUPS.forEach(g => {
    const wrap = document.createElement("div");
    wrap.className = "group" + (g.lens === state.lens ? " open" : "");
    wrap.dataset.group = g.lens;
    wrap.innerHTML = `
      <button class="group-head">
        <span class="caret">▸</span>${esc(g.label)}
        <span class="badge" hidden></span>
        ${g.pending ? '<em class="soon">soon</em>' : ""}
      </button>
      <div class="group-body"></div>`;
    host.appendChild(wrap);
    const body = wrap.querySelector(".group-body");
    wrap.querySelector(".group-head").onclick = () => wrap.classList.toggle("open");

    if (g.pending) {
      body.innerHTML = `<p class="pending-note">${
        g.filters.map(f => esc(f.label)).join(" · ")} — available once Phase ${
        g.lens === "provision" ? "2" : "3"} data is ingested.</p>`;
      return;
    }

    g.filters.forEach(f => {
      const [lo, hi] = ranges[f.key];
      const el = document.createElement("div");
      el.className = "slider";
      el.innerHTML = `
        <div class="head">
          <span class="name">${esc(f.label)}</span>
          <span class="val"></span>
        </div>
        <div class="track">
          <div class="rail-bg"></div><div class="rail-fill"></div>
          <input type="range" class="lo" min="${lo}" max="${hi}" step="any" value="${lo}">
          <input type="range" class="hi" min="${lo}" max="${hi}" step="any" value="${hi}">
        </div>`;
      body.appendChild(el);

      const [inLo, inHi] = [el.querySelector(".lo"), el.querySelector(".hi")];
      const fill = el.querySelector(".rail-fill");
      const sync = () => {
        let a = +inLo.value, b = +inHi.value;
        if (a > b) { [a, b] = [b, a]; }
        state.filters[f.key] = [a, b];
        const p = v => ((v - lo) / (hi - lo)) * 100;
        fill.style.left = p(a) + "%";
        fill.style.width = (p(b) - p(a)) + "%";
        const u = f.unit || "";
        el.querySelector(".val").textContent =
          `${d3.format(",." + f.dp + "f")(a)}${u} – ${d3.format(",." + f.dp + "f")(b)}${u}`;
        el.classList.toggle("dirty", a > lo || b < hi);
        render();
      };
      inLo.oninput = inHi.oninput = sync;
      sync();
    });
  });
}

function passes(d) {
  return ALL_FILTERS.every(f => {
    const v = d[f.key];
    if (v == null) return true;
    const range = state.filters[f.key];
    if (!range) return true;
    return v >= range[0] && v <= range[1];
  });
}

function updateBadges() {
  FILTER_GROUPS.forEach(g => {
    const el = document.querySelector(`.group[data-group="${g.lens}"] .badge`);
    if (!el) return;
    const n = g.pending ? 0 : g.filters.filter(f => {
      const [a, b] = state.filters[f.key] || [];
      const [lo, hi] = extent(f.key);
      return a > lo || b < hi;
    }).length;
    el.hidden = !n;
    el.textContent = n;
  });
}

/* ---------------- time axis ---------------- */

function buildTimeAxis() {
  const host = $("timeaxis");
  if (lens().time === "census") {
    host.innerHTML = `
      <span class="scrub-label">Census</span>
      <div class="segmented" id="period">
        <button data-period="2011" class="${state.period === PREV ? "on" : ""}">2011</button>
        <button data-period="2021" class="${state.period === NOW ? "on" : ""}">2021</button>
      </div>
      <span class="scrub-label" style="margin-left:18px">Share basis</span>
      <div class="segmented" id="basisbtn">
        <button data-basis="sr" class="${state.basis === "sr" ? "on" : ""}">Respondents</button>
        <button data-basis="sa" class="${state.basis === "sa" ? "on" : ""}">All residents</button>
      </div>`;
    d3.selectAll("#period button").on("click", function () {
      state.period = this.dataset.period;
      d3.selectAll("#period button").classed("on", false);
      d3.select(this).classed("on", true);
      render();
    });
    d3.selectAll("#basisbtn button").on("click", function () {
      state.basis = this.dataset.basis;
      d3.selectAll("#basisbtn button").classed("on", false);
      d3.select(this).classed("on", true);
      render();
    });
  } else {
    // Activity runs on continuous time, so it gets its own control rather than
    // overloading the census toggle to mean two different things.
    host.innerHTML = `
      <span class="scrub-label">Window</span>
      <div class="segmented" id="window">
        ${[12, 24, 60].map(m =>
          `<button data-w="${m}" class="${state.window === m ? "on" : ""}">${m} months</button>`).join("")}
      </div>
      <span class="stamp">no snapshot ingested</span>`;
    d3.selectAll("#window button").on("click", function () {
      state.window = +this.dataset.w;
      d3.selectAll("#window button").classed("on", false);
      d3.select(this).classed("on", true);
      render();
    });
  }
}

/* ---------------- map ---------------- */

function setupMap() {
  svg = d3.select("#map");
  canvas = $("dots");
  ctx = canvas.getContext("2d");
  gMap = svg.append("g");

  projection = d3.geoMercator();
  path = d3.geoPath(projection);

  gMap.selectAll("path")
    .data(GEO.features)
    .join("path")
      .attr("class", "district")
      .attr("data-code", f => f.properties.LAD24CD)
      .on("click", (e, f) => select(f.properties.LAD24CD))
      .append("title");

  const zoom = d3.zoom().scaleExtent([1, 20]).on("zoom", e => {
    state.transform = e.transform;
    gMap.attr("transform", e.transform);
    drawCanvas();
  });
  svg.call(zoom);
  svg.node().__zoom__ = zoom;

  new ResizeObserver(() => { fit(); render(); }).observe($("mapwrap"));
  fit();
}

function fit() {
  const w = $("mapwrap").clientWidth, h = $("mapwrap").clientHeight;
  if (!w || !h) return;
  svg.attr("viewBox", `0 0 ${w} ${h}`);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr; canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  projection.fitExtent([[12, 12], [w - 12, h - 12]], GEO);
  if (gMap) gMap.selectAll("path.district").attr("d", path);
  dotCache.clear();
}

function scaleFor() {
  const vals = GEO.features
    .map(f => value(DATA.districts[f.properties.LAD24CD]))
    .filter(v => v != null);
  const m = METRICS[state.metric];
  if (!vals.length) return null;
  if (m.diverging) {
    const lim = d3.max(vals.map(Math.abs)) || 1;
    return d3.scaleDiverging(d3.interpolateRgbBasis(["#4b8fd6", "#1b2430", "#e2703a"]))
             .domain([-lim, 0, lim]);
  }
  // clamp the top to the 98th percentile so one outlier does not flatten the ramp
  const hi = d3.quantile(vals.slice().sort(d3.ascending), 0.98) || d3.max(vals);
  return d3.scaleSequential(
      d3.interpolateRgbBasis(["#101820", "#12414a", "#18787a", "#2ab5ac", "#7df2e4"]))
    .domain([d3.min(vals), hi]).clamp(true);
}

function render() {
  colorScale = scaleFor();
  const pending = lensPending();
  const shown = [];

  svg.attr("class", "mode-" + state.mode + (pending ? " pending" : ""));
  gMap.selectAll("path.district").each(function (f) {
    const code = f.properties.LAD24CD;
    const d = DATA.districts[code];
    const ok = passes(d);
    if (ok) shown.push(code);
    const v = colorScale ? value(d) : null;
    d3.select(this)
      .attr("fill", v == null ? "#131a23" : colorScale(v))
      .classed("dim", !ok)
      .classed("sel", state.selected === code);
    this.querySelector("title").textContent = `${d.n} — ${fmtVal(v)}`;
  });

  $("shown").textContent = shown.length;
  updateBadges();
  drawCanvas();
  renderLegend();
  renderEmpty();
  renderMethod();
}

function renderEmpty() {
  const el = $("empty-state");
  const e = lensPending() ? lens().empty : null;
  el.hidden = !e;
  if (e) el.innerHTML = `<div class="es-card">
      <h3>${esc(e.title)}</h3><p>${e.body}</p>
      <p class="es-foot">The district shapes, filters and selection stay live, so
      the shell can be checked before the data lands.</p></div>`;
}

function fmtVal(v) {
  if (v == null) return "no data";
  const m = METRICS[state.metric];
  const s = d3.format(",." + m.dp + "f")(v);
  return (v > 0 && m.diverging ? "+" : "") + s + (m.unit || "");
}

/* ---------------- canvas renders ---------------- */

function rng(seed) {
  let s = seed >>> 0;
  return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296;
}

const dotCache = new Map();

function dotsFor(code) {
  const key = code + "|" + state.period;
  if (dotCache.has(key)) return dotCache.get(key);

  const d = DATA.districts[code];
  const pts = POINTS[code];
  const n = state.period === PREV ? d.c11 : d.c;
  if (!pts || !n) { dotCache.set(key, []); return []; }

  const cum = [];
  let total = 0;
  for (const p of pts.p) { total += p; cum.push(total); }

  const count = Math.round(n / DOT_PEOPLE);
  const rand = rng(hash(code));
  const out = [];
  for (let i = 0; i < count; i++) {
    const t = rand() * total;
    let lo = 0, hi = cum.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; cum[mid] < t ? lo = mid + 1 : hi = mid; }
    out.push([pts.x[lo] + (rand() - .5) * .012, pts.y[lo] + (rand() - .5) * .008]);
  }
  dotCache.set(key, out);
  return out;
}

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

function drawCanvas() {
  const w = $("mapwrap").clientWidth, h = $("mapwrap").clientHeight;
  ctx.clearRect(0, 0, w, h);
  // dot renders describe the census population, so they stay put in every lens
  if (state.mode === "choropleth") return;

  const t = state.transform;
  const heat = state.mode === "heat";
  ctx.save();
  if (heat) ctx.globalCompositeOperation = "lighter";

  for (const f of GEO.features) {
    const code = f.properties.LAD24CD;
    if (!passes(DATA.districts[code])) continue;
    const dots = dotsFor(code);
    if (!dots.length) continue;

    if (heat) {
      const r = Math.max(6, 13 * Math.sqrt(t.k));
      for (const [lon, lat] of dots) {
        const p = projection([lon, lat]);
        if (!p) continue;
        const x = p[0] * t.k + t.x, y = p[1] * t.k + t.y;
        if (x < -r || y < -r || x > w + r || y > h + r) continue;
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, "rgba(55,200,195,.16)");
        g.addColorStop(1, "rgba(55,200,195,0)");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, r, 0, 6.283); ctx.fill();
      }
    } else {
      ctx.fillStyle = "rgba(94,240,228,.72)";
      const r = Math.max(.55, .85 * Math.sqrt(t.k));
      for (const [lon, lat] of dots) {
        const p = projection([lon, lat]);
        if (!p) continue;
        const x = p[0] * t.k + t.x, y = p[1] * t.k + t.y;
        if (x < 0 || y < 0 || x > w || y > h) continue;
        ctx.beginPath(); ctx.arc(x, y, r, 0, 6.283); ctx.fill();
      }
    }
  }
  ctx.restore();
}

/* ---------------- legend + method ---------------- */

function renderLegend() {
  if (!colorScale) {
    $("legend").innerHTML =
      `<div class="title">${esc(metricLabel())}</div><div class="nodata">awaiting data</div>`;
    return;
  }
  const m = METRICS[state.metric];
  const dom = colorScale.domain();
  const [a, b] = m.diverging ? [dom[0], dom[2]] : dom;
  const ramp = d3.range(28)
    .map(i => `<i style="background:${colorScale(a + (b - a) * i / 27)}"></i>`).join("");
  const dotNote = state.mode === "choropleth" ? "" :
    `<div class="ln">1 dot ≈ ${fmt(DOT_PEOPLE)} people · placed by LSOA population,
      coloured by district figure</div>`;
  $("legend").innerHTML = `
    <div class="title">${esc(metricLabel())}</div>
    <div class="ramp">${ramp}</div>
    <div class="ticks"><span>${fmtVal(a)}</span><span>${fmtVal(b)}</span></div>
    ${dotNote}`;
}

function renderMethod() {
  const b = DATA.baselines;
  const l = lens();
  let s;
  if (l.id === "provision") {
    s = `<b>Provision is service capacity, not encroachment</b> — worshippers per
      mosque, mapped the way GP surgeries or schools are. Source registers
      undercount unevenly across faiths, so figures will ship as a range across
      tiers rather than a point estimate.`;
  } else if (l.id === "activity") {
    s = `<b>Applications are applications</b> — refused and withdrawn stay visible,
      and an approval is not a building. There is no reliable mosque stock time
      series, so change is measured as planning flow, never as a difference
      between two register snapshots.`;
  } else {
    s = `<b>Religion is the census's only voluntary question</b> — ${b.nrp}% of
      England &amp; Wales did not answer. Shares are shown on both bases:
      all residents (${b.sa}%) and respondents only (${b.sr}%) nationally.`;
    if (state.period === PREV) s += ` Showing <b>2011</b>; only population and
      Muslim count/share have a 2011 equivalent.`;
    if (state.mode !== "choropleth") s += ` Dots use sub-district population only;
      no religion data below district level is used.`;
  }
  $("method").innerHTML = s;
}

/* ---------------- detail panel ---------------- */

function select(code) {
  state.selected = state.selected === code ? null : code;
  render();
  renderPanel();
}

function delta(v, dp = 1, unit = "") {
  if (v == null) return `<span class="v">—</span>`;
  const cls = v > 0 ? "up" : v < 0 ? "down" : "";
  return `<span class="v ${cls}">${v > 0 ? "+" : ""}${d3.format("." + dp + "f")(v)}${unit}</span>`;
}

const TABS = [
  { id: "dem", label: "Demography" },
  { id: "pro", label: "Provision", pending: true },
  { id: "act", label: "Activity", pending: true },
];

function renderPanel() {
  const panel = $("panel");
  if (!state.selected) {
    panel.classList.add("empty");
    $("panel-head").innerHTML = ""; $("panel-tabs").innerHTML = ""; $("panel-body").innerHTML = "";
    return;
  }
  panel.classList.remove("empty");
  const d = DATA.districts[state.selected];

  // header stays constant across tabs so context is never lost
  $("panel-head").innerHTML = `
    <h3>${esc(d.n)}</h3>
    <div class="code">${esc(state.selected)} · ltla23</div>
    <div class="p-strip">
      <span><b>${fmt(d.pop)}</b> residents</span>
      <span><b>${fmt(d.c)}</b> Muslim</span>
      <span><b>${fmt1(d.sa)}%</b></span>
    </div>`;

  $("panel-tabs").innerHTML = TABS.map(t =>
    `<button data-tab="${t.id}" class="${t.id === state.tab ? "on" : ""}">
      ${esc(t.label)}${t.pending ? '<i class="dot"></i>' : ""}</button>`).join("");
  d3.selectAll("#panel-tabs button").on("click", function () {
    state.tab = this.dataset.tab; renderPanel();
  });

  $("panel-body").innerHTML =
    state.tab === "dem" ? panelDemography(d) :
    state.tab === "pro" ? panelPending("provision", d) : panelPending("activity", d);
}

function panelPending(which, d) {
  const e = LENSES.find(l => l.id === which).empty;
  const extra = which === "provision"
    ? `<div class="rows">
         <span class="k">Mosques</span><span class="v">—</span><span class="b"></span>
         <span class="k">Muslims per mosque</span><span class="v">—</span><span class="b"></span>
       </div>`
    : `<div class="rows">
         <span class="k">Applications, ${state.window} months</span><span class="v">—</span><span class="b"></span>
         <span class="k">Approved / refused</span><span class="v">—</span><span class="b"></span>
       </div>`;
  return `<div class="p-sec">
      <h4>${esc(which)}</h4>
      ${extra}
      <div class="flag">${esc(e.title)}. ${e.body}</div>
    </div>`;
}

function panelDemography(d) {
  const b = DATA.baselines, nat = b.faiths.Muslim;
  const faithTotal = d3.sum(Object.values(d.f));
  const order = ["Christian", "Muslim", "No religion", "Hindu", "Sikh", "Jewish",
                 "Buddhist", "Other religion", "Not answered"];
  const stack = order.filter(k => d.f[k]).map(k =>
    `<i style="background:${FAITH_COLORS[k]};width:${d.f[k] / faithTotal * 100}%" title="${k}"></i>`).join("");
  const key = order.filter(k => d.f[k]).slice(0, 6).map(k =>
    `<div class="kk"><span class="sw" style="background:${FAITH_COLORS[k]}"></span>
      ${esc(k)}<span class="kv">${fmt1(d.f[k] / faithTotal * 100)}%</span></div>`).join("");
  const eth = d.eth.length ? d.eth.map(([name, pct]) => `
    <div class="bar-row">
      <span class="lab" title="${esc(name)}">${esc(name.split(": ").pop())}</span>
      <span class="pct">${fmt1(pct)}%</span>
      <span class="bar-track"><span class="bar-fill" style="width:${Math.min(100, pct)}%"></span></span>
    </div>`).join("") : `<p class="p-sub">Suppressed — fewer than 1,000 Muslim residents.</p>`;

  return `
    <div class="p-sec">
      <h4>Muslim population</h4>
      <div class="big"><span class="v">${fmt(d.c)}</span><span class="u">residents</span></div>
      <div class="big" style="margin-top:8px">
        <span class="v">${fmt1(d.sa)}%</span><span class="u">of all residents</span>
      </div>
      <p class="p-sub">${fmt1(d.sr)}% of those who answered the religion question.
        ${fmt1(d.nrp)}% of this district did not answer (national ${b.nrp}%).</p>
      ${d.sup ? `<div class="flag">Rate suppressed: ${esc(d.sup)}. Counts are
        published; per-capita figures are not meaningful at this size.</div>` : ""}
    </div>

    <div class="p-sec">
      <h4>Change since 2011</h4>
      <div class="rows">
        <span class="k">Muslim population</span>
        <span class="v">${d.c11 ? fmt(d.c11) + " → " + fmt(d.c) : "—"}</span><span class="b"></span>
        <span class="k">Share of respondents</span>
        <span class="v">${d.sr11 != null ? fmt1(d.sr11) + "% → " + fmt1(d.sr) + "%" : "—"}</span><span class="b"></span>
        <span class="k">Change, percentage points</span>${delta(d.dpp, 1, "pp")}<span class="b"></span>
        <span class="k">Change, relative</span>${delta(d.drel, 0, "%")}<span class="b">${b.drel}%</span>
      </div>
      <p class="p-sub" style="margin-top:8px">Both forms are shown because they
        answer different questions — a large relative rise on a small base is not
        a large change in composition.</p>
    </div>

    <div class="p-sec">
      <h4>Who</h4>
      <div class="rows">
        <span class="k">Median age</span>
        <span class="v">${d.med != null ? fmt1(d.med) : "—"}</span><span class="b">${nat.med}</span>
        <span class="k">Under 16</span>
        <span class="v">${d.u16 != null ? fmt1(d.u16) + "%" : "—"}</span><span class="b">${nat.u16}%</span>
        <span class="k">UK-born</span>
        <span class="v">${d.ukb != null ? fmt1(d.ukb) + "%" : "—"}</span><span class="b">${nat.ukb}%</span>
      </div>
      <p class="p-sub" style="margin-top:8px">Median age is interpolated from 23
        census age bands, so it is close to but not identical with the ONS median.</p>
    </div>

    <div class="p-sec">
      <h4>Ethnic composition of the Muslim population</h4>
      <div class="bars">${eth}</div>
    </div>

    <div class="p-sec">
      <h4>All religions in this district</h4>
      <div class="stack">${stack}</div>
      <div class="stack-key">${key}</div>
    </div>

    <div class="p-sec">
      <h4>Sources</h4>
      <p class="cite">Census 2021 <b>TS030</b> (Nomis NM_2049_1) · Census 2011
        <b>KS209EW</b> (NM_616_1), summed onto April-2023 districts · age and
        country of birth from the ONS custom-dataset API (<b>resident_age_23a</b>,
        <b>country_of_birth_8a</b>) · ethnic group <b>ethnic_group_tb_20b</b>.
        Counts are subject to census disclosure control and may differ by a few
        people from published totals.</p>
    </div>`;
}

/* ---------------- controls ---------------- */

function wireControls() {
  $("metric").onchange = () => { state.metric = $("metric").value; render(); };

  d3.selectAll("#render button").on("click", function () {
    state.mode = this.dataset.mode;
    d3.selectAll("#render button").classed("on", false);
    d3.select(this).classed("on", true);
    render();
  });

  $("reset").onclick = () => { buildSliders(); applyLens(state.lens, true); };

  d3.selectAll("#zoomctl button").on("click", function () {
    const z = svg.node().__zoom__;
    if (this.dataset.z === "reset") svg.transition().duration(300).call(z.transform, d3.zoomIdentity);
    else svg.transition().duration(220).call(z.scaleBy, +this.dataset.z);
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && state.selected) select(state.selected);
    const i = ["1", "2", "3"].indexOf(e.key);
    if (i >= 0 && e.target.tagName !== "INPUT") applyLens(LENSES[i].id);
  });
}
