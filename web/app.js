/* Islam in Britain — census map.
 *
 * Three renders over the same district data, because a choropleth alone
 * misleads on this dataset: it shades land, and English districts vary
 * enormously in physical size, so sparse rural areas read as significant and
 * dense urban ones vanish. Dot density and the heat surface place marks by
 * where people actually live (LSOA population-weighted centroids) and are the
 * honest default; the choropleth is kept because it is the conventional view.
 *
 * Both share bases are always available and the panel shows them together.
 * See DESIGN.md — the respondent basis drives the scale, the all-residents
 * basis is what reconciles with published ONS figures.
 */

const DOT_PEOPLE = 150;       // one dot = this many people
const PREV = "2011", NOW = "2021";

const state = {
  metric: "sr",
  mode: "choropleth",
  period: NOW,
  basis: "sr",
  selected: null,
  filters: {},        // key -> [lo, hi]
  transform: d3.zoomIdentity,
};

let DATA, GEO, POINTS, features, path, projection;
let svg, gMap, canvas, ctx, colorScale;

const $ = id => document.getElementById(id);
const fmt = d3.format(",");
const fmt1 = d3.format(".1f");
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

/* ---------------- metrics ---------------- */

// `prev` names the field to use when the scrubber is on 2011; metrics without
// one are census-2021-only and say so rather than silently showing 2021 data.
const METRICS = {
  sr:   { label: "Muslim share of respondents", unit: "%", basis: true,
          prev: "sr11", diverging: false, dp: 1 },
  c:    { label: "Muslim population", unit: "", prev: "c11", dp: 0 },
  k:    { label: "Muslims per 10,000 respondents", unit: "", dp: 0 },
  dpp:  { label: "Change since 2011 (percentage points)", unit: "pp", diverging: true, dp: 1 },
  drel: { label: "Change since 2011 (relative)", unit: "%", diverging: true, dp: 0 },
  med:  { label: "Median age (Muslim)", unit: "", dp: 1 },
  u16:  { label: "Under 16 (Muslim)", unit: "%", dp: 1 },
  ukb:  { label: "UK-born (Muslim)", unit: "%", dp: 1 },
  nrp:  { label: "Religion question not answered", unit: "%", dp: 1 },
  pop:  { label: "Total population", unit: "", prev: "p11", dp: 0 },
};

// Filter rail. Every range here is a plain field on the district record.
const FILTERS = [
  { key: "pop", label: "Total population", dp: 0 },
  { key: "c",   label: "Muslim population", dp: 0 },
  { key: "sr",  label: "Share of respondents", unit: "%", dp: 1 },
  { key: "dpp", label: "Change since 2011", unit: "pp", dp: 1 },
  { key: "med", label: "Median age", dp: 1 },
  { key: "ukb", label: "UK-born", unit: "%", dp: 1 },
  { key: "nrp", label: "Not answered", unit: "%", dp: 1 },
];

const FAITH_COLORS = {
  "Muslim": "#37c8c3", "Christian": "#5b7fa6", "No religion": "#3e4a5a",
  "Hindu": "#c9803f", "Sikh": "#8a6fb0", "Jewish": "#a8b04f",
  "Buddhist": "#4f9e7a", "Other religion": "#6d7482", "Not answered": "#2a323d",
};

/* metric value for a district, honouring period + basis */
function value(d, key = state.metric) {
  const m = METRICS[key];
  if (!m) return null;
  if (state.period === PREV) {
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
  // England & Wales only for now — Scotland comes from NRS, see DESIGN.md.
  GEO = { type: "FeatureCollection",
          features: geo.features.filter(f => DATA.districts[f.properties.LAD24CD]) };
  init();
});

function init() {
  buildMetricSelect();
  setupMap();      // before buildSliders: its sync() calls render(), which needs the svg
  buildSliders();
  wireControls();
  render();
  renderMethod();
}

function buildMetricSelect() {
  const sel = $("metric");
  sel.innerHTML = Object.entries(METRICS)
    .map(([k, m]) => `<option value="${k}">${esc(m.label)}</option>`).join("");
  sel.value = state.metric;
  sel.onchange = () => { state.metric = sel.value; render(); renderMethod(); };
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
  FILTERS.forEach(f => { ranges[f.key] = extent(f.key); state.filters[f.key] = ranges[f.key]; });

  FILTERS.forEach(f => {
    const [lo, hi] = ranges[f.key];
    // step="any": a fixed step snaps the max handle a step below the true
    // maximum through float error, which silently drops the top district.

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
    host.appendChild(el);

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
}

function passes(d) {
  return FILTERS.every(f => {
    const v = d[f.key];
    if (v == null) return true;              // missing data is not a filter fail
    const range = state.filters[f.key];
    if (!range) return true;
    const [a, b] = range;
    return v >= a && v <= b;
  });
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
  // the projection changed, so every path has to be regenerated
  if (gMap) gMap.selectAll("path.district").attr("d", path);
  dotCache.clear();
}

function scaleFor() {
  const vals = GEO.features
    .map(f => value(DATA.districts[f.properties.LAD24CD]))
    .filter(v => v != null);
  const m = METRICS[state.metric];
  if (m.diverging) {
    const lim = d3.max(vals.map(Math.abs)) || 1;
    return d3.scaleDiverging(d3.interpolateRgbBasis(["#4b8fd6", "#1b2430", "#e2703a"]))
             .domain([-lim, 0, lim]);
  }
  // quantile-ish: clamp the top to the 98th percentile so one outlier district
  // does not flatten the whole ramp (Tower Hamlets does exactly this on share)
  const hi = d3.quantile(vals.slice().sort(d3.ascending), 0.98) || d3.max(vals);
  return d3.scaleSequential(
      d3.interpolateRgbBasis(["#101820", "#12414a", "#18787a", "#2ab5ac", "#7df2e4"]))
    .domain([d3.min(vals), hi]).clamp(true);
}

function render() {
  colorScale = scaleFor();
  const shown = [];

  svg.attr("class", "mode-" + state.mode);
  gMap.selectAll("path.district").each(function (f) {
    const code = f.properties.LAD24CD;
    const d = DATA.districts[code];
    const ok = passes(d);
    if (ok) shown.push(code);
    const v = value(d);
    const el = d3.select(this);
    el.attr("fill", v == null ? "#131a23" : colorScale(v))
      .classed("dim", !ok)
      .classed("sel", state.selected === code);
    this.querySelector("title").textContent =
      `${d.n} — ${fmtVal(v)}`;
  });

  $("shown").textContent = shown.length;
  drawCanvas();
  renderLegend();
}

function fmtVal(v) {
  if (v == null) return "no data";
  const m = METRICS[state.metric];
  const s = d3.format(",." + m.dp + "f")(v);
  return (v > 0 && m.diverging ? "+" : "") + s + (m.unit || "");
}

/* ---------------- canvas renders ---------------- */

// deterministic PRNG so dots do not jump on every redraw
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

  // weighted sampling across LSOA centroids: dots land where people live
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
    // jitter within roughly an LSOA so dots do not stack on the centroid
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
  if (state.mode === "choropleth") return;

  const t = state.transform;
  const heat = state.mode === "heat";
  ctx.save();
  if (heat) ctx.globalCompositeOperation = "lighter";

  for (const f of GEO.features) {
    const code = f.properties.LAD24CD;
    const d = DATA.districts[code];
    if (!passes(d)) continue;
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

/* ---------------- legend ---------------- */

function renderLegend() {
  const m = METRICS[state.metric];
  const dom = colorScale.domain();
  const [a, b] = m.diverging ? [dom[0], dom[2]] : dom;
  const steps = 28;
  const ramp = d3.range(steps)
    .map(i => `<i style="background:${colorScale(a + (b - a) * i / (steps - 1))}"></i>`)
    .join("");
  const dotNote = state.mode === "choropleth" ? "" :
    `<div style="margin-top:7px">1 dot ≈ ${fmt(DOT_PEOPLE)} people · placed by
     LSOA population, coloured by district figure</div>`;
  $("legend").innerHTML = `
    <div class="title">${esc(metricLabel())}</div>
    <div class="ramp">${ramp}</div>
    <div class="ticks"><span>${fmtVal(a)}</span><span>${fmtVal(b)}</span></div>
    ${dotNote}`;
}

function renderMethod() {
  const m = METRICS[state.metric];
  const b = DATA.baselines;
  let s = `<b>Religion is the census's only voluntary question</b> — ${b.nrp}% of
    England &amp; Wales did not answer. Shares are shown on both bases:
    all residents (${b.sa}%) and respondents only (${b.sr}%) nationally.`;
  if (state.period === PREV) {
    s += ` Showing <b>2011</b>; only population and Muslim count/share have a
      2011 equivalent.`;
  }
  if (!m.prev && state.period === PREV) {
    s += ` <b>${esc(m.label)} has no 2011 figure</b> — the map is blank.`;
  }
  if (state.mode !== "choropleth") {
    s += ` Dots are placed using sub-district population only; no religion data
      below district level is used.`;
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

function renderPanel() {
  const panel = $("panel");
  if (!state.selected) { panel.classList.add("empty"); $("panel-body").innerHTML = ""; return; }
  panel.classList.remove("empty");

  const d = DATA.districts[state.selected];
  const b = DATA.baselines;
  const nat = b.faiths.Muslim;

  const faithTotal = d3.sum(Object.values(d.f));
  const order = ["Christian", "Muslim", "No religion", "Hindu", "Sikh", "Jewish",
                 "Buddhist", "Other religion", "Not answered"];
  const stack = order.filter(k => d.f[k]).map(k =>
    `<i style="background:${FAITH_COLORS[k]};width:${d.f[k] / faithTotal * 100}%" title="${k}"></i>`
  ).join("");
  const key = order.filter(k => d.f[k]).slice(0, 6).map(k =>
    `<div class="kk"><span class="sw" style="background:${FAITH_COLORS[k]}"></span>
      ${esc(k)}<span class="kv">${fmt1(d.f[k] / faithTotal * 100)}%</span></div>`
  ).join("");

  const eth = d.eth.length ? d.eth.map(([name, pct]) => `
    <div class="bar-row">
      <span class="lab" title="${esc(name)}">${esc(name.split(": ").pop())}</span>
      <span class="pct">${fmt1(pct)}%</span>
      <span class="bar-track"><span class="bar-fill" style="width:${Math.min(100, pct)}%"></span></span>
    </div>`).join("") : `<p class="p-sub">Suppressed — fewer than 1,000 Muslim residents.</p>`;

  $("panel-body").innerHTML = `
    <div class="p-head">
      <h3>${esc(d.n)}</h3>
      <div class="code">${esc(state.selected)} · ltla23</div>
    </div>

    <div class="p-sec">
      <h4>Muslim population</h4>
      <div class="big"><span class="v">${fmt(d.c)}</span><span class="u">residents</span></div>
      <div class="big" style="margin-top:8px">
        <span class="v">${fmt1(d.sa)}%</span>
        <span class="u">of all residents</span>
      </div>
      <p class="p-sub">
        ${fmt1(d.sr)}% of those who answered the religion question.
        ${fmt1(d.nrp)}% of this district did not answer
        (national ${b.nrp}%).
      </p>
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
        <span class="k">Change, percentage points</span>
        ${delta(d.dpp, 1, "pp")}<span class="b"></span>
        <span class="k">Change, relative</span>
        ${delta(d.drel, 0, "%")}<span class="b">${b.drel}%</span>
      </div>
      <p class="p-sub" style="margin-top:8px">
        Both forms are shown because they answer different questions — a large
        relative rise on a small base is not a large change in composition.
      </p>
    </div>

    <div class="p-sec">
      <h4>Who</h4>
      <div class="rows">
        <span class="k">Median age</span>
        <span class="v">${d.med != null ? fmt1(d.med) : "—"}</span>
        <span class="b">${nat.med}</span>
        <span class="k">Under 16</span>
        <span class="v">${d.u16 != null ? fmt1(d.u16) + "%" : "—"}</span>
        <span class="b">${nat.u16}%</span>
        <span class="k">UK-born</span>
        <span class="v">${d.ukb != null ? fmt1(d.ukb) + "%" : "—"}</span>
        <span class="b">${nat.ukb}%</span>
      </div>
      <p class="p-sub" style="margin-top:8px">
        Median age is interpolated from 23 census age bands, so it is close to
        but not identical with the ONS published median.
      </p>
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
      <p class="cite">
        Census 2021 table <b>TS030</b> (Nomis NM_2049_1) · Census 2011
        <b>KS209EW</b> (NM_616_1), summed onto April-2023 districts ·
        age and country of birth from the ONS custom-dataset API
        (<b>resident_age_23a</b>, <b>country_of_birth_8a</b>) · ethnic group
        <b>ethnic_group_tb_20b</b>. Counts are subject to census disclosure
        control and may differ by a few people from published totals.
      </p>
    </div>`;
}

/* ---------------- controls ---------------- */

function wireControls() {
  d3.selectAll("#render button").on("click", function () {
    state.mode = this.dataset.mode;
    d3.selectAll("#render button").classed("on", false);
    d3.select(this).classed("on", true);
    render(); renderMethod();
  });

  d3.selectAll("#period button").on("click", function () {
    state.period = this.dataset.period;
    d3.selectAll("#period button").classed("on", false);
    d3.select(this).classed("on", true);
    render(); renderMethod();
  });

  d3.selectAll("#basisbtn button").on("click", function () {
    state.basis = this.dataset.basis;
    d3.selectAll("#basisbtn button").classed("on", false);
    d3.select(this).classed("on", true);
    render(); renderLegend(); renderMethod();
  });

  $("reset").onclick = () => { buildSliders(); render(); };

  d3.selectAll("#zoomctl button").on("click", function () {
    const z = svg.node().__zoom__;
    if (this.dataset.z === "reset") svg.transition().duration(300).call(z.transform, d3.zoomIdentity);
    else svg.transition().duration(220).call(z.scaleBy, +this.dataset.z);
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && state.selected) select(state.selected);
  });
}
