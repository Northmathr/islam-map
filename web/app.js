/* Mosques in England & Wales.
 *
 * The map answers three counting questions, and everything on screen serves
 * one of them:
 *
 *   1. How many mosques are there, and where?
 *   2. How has that changed over time?
 *   3. What is in planning now?
 *
 * Deliberately plain. One render (choropleth), raw counts rather than
 * percentages, and a year slider as the only mode of exploration. Shares of
 * respondents versus all residents were removed: the question is "how many",
 * and two competing denominators answered a question nobody was asking.
 *
 * The time series comes from planning records, not from a register: nobody
 * publishes a historical count of mosques. So "change over time" means
 * approved planning outcomes accumulated year by year, which is a real
 * measurement of a real process, and is labelled as exactly that.
 */

const FIRST_YEAR = 2000;
const CENSUS_YEAR = 2021, CENSUS_PREV = 2011;

const state = {
  metric: "mq",
  year: null,
  overlays: { mosques: true, applications: true },
  selected: null,
  playing: false,
  transform: d3.zoomIdentity,
};

let DATA, GEO, MOSQUES, APPS, projection, path;
let svg, gMap, canvas, ctx, colorScale, YEARS, byYear, cumulative, timer;

const $ = id => document.getElementById(id);
const fmt = d3.format(",");
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const KIND_LABEL = {
  new_build: "New build or replacement", use_to: "Converted to a mosque",
  extension: "Extension or alteration", use_away: "Converted to something else",
  demolition: "Demolished, not replaced", admin: "Conditions or amendments",
  other: "Other",
};
// only these change the number of mosques; extensions and paperwork do not
const GAIN = { new_build: 1, use_to: 1, use_away: -1, demolition: -1 };

const METRICS = {
  mq:    { label: "Mosques", short: "mosques", dp: 0,
           get: d => d.mq },
  mqc:   { label: "Mosques confirmed by 2+ sources", short: "confirmed", dp: 0,
           get: d => d.mqc },
  gain:  { label: "Mosques approved, running total", short: "approved to date", dp: 0,
           diverging: true, get: d => cum(d.code).net },
  apps:  { label: "Planning applications that year", short: "applications", dp: 0,
           get: d => (byYear[state.year] || {})[d.code]?.n || 0 },
  live:  { label: "Applications awaiting a decision", short: "awaiting decision", dp: 0,
           get: d => d.pending },
  pop:   { label: "Muslim residents (census)", short: "Muslim residents", dp: 0,
           get: d => d.c },
  per:   { label: "Muslim residents per mosque", short: "residents per mosque", dp: 0,
           get: d => d.ratio },
};

const OVERLAYS = [
  { id: "mosques", label: "Mosques", color: () => css("--mosque") },
  { id: "applications", label: "Applications", color: () => css("--accent") },
];

const STATUS_LABEL = { approved: "Approved", refused: "Refused",
                       withdrawn: "Withdrawn", pending: "Awaiting decision" };
// Legend-only abbreviations for narrow screens; the panel keeps the full words.
const NATION = { E: "England", W: "Wales", S: "Scotland", N: "Northern Ireland" };
const STATUS_SHORT = { approved: "Approved", refused: "Refused",
                       withdrawn: "Withdrawn", pending: "Pending" };
const statusColor = s => ({ approved: css("--ok"), refused: css("--up"),
                            withdrawn: css("--ink-3"), pending: css("--warn") }[s] || css("--ink-3"));

/* ---------------- boot ---------------- */

const NOCACHE = { cache: "no-cache" };
Promise.all([
  d3.json("data/districts.json", NOCACHE),
  d3.json("data/lad_boundaries.json", NOCACHE),
  d3.json("data/mosques.json", NOCACHE),
  d3.json("data/applications.json", NOCACHE),
]).then(([data, geo, mosques, apps]) => {
  DATA = data; MOSQUES = mosques; APPS = apps;
  for (const [code, d] of Object.entries(DATA.districts)) d.code = code;
  GEO = { type: "FeatureCollection",
          features: geo.features.filter(f => DATA.districts[f.properties.LAD24CD]) };
  prepare();
  init();
});

/* ---------------- time series ---------------- */

function prepare() {
  const years = APPS.records.map(r => +r.d.slice(0, 4)).filter(y => y >= FIRST_YEAR);
  const last = Math.max(...years);
  YEARS = d3.range(FIRST_YEAR, last + 1);
  state.year = last;

  // per-year, per-district counts
  byYear = {};
  for (const y of YEARS) byYear[y] = {};
  for (const r of APPS.records) {
    const y = +r.d.slice(0, 4);
    if (!byYear[y]) continue;
    const o = byYear[y][r.c] || (byYear[y][r.c] = { n: 0, approved: 0, refused: 0,
                                                    withdrawn: 0, pending: 0, net: 0, kinds: {} });
    o.n++; o[r.s]++;
    o.kinds[r.k] = (o.kinds[r.k] || 0) + 1;
    if (r.s === "approved") o.net += GAIN[r.k] || 0;
  }

  // running totals, so the slider reads as an accumulating estate
  cumulative = {};
  const acc = {};
  for (const y of YEARS) {
    for (const [code, o] of Object.entries(byYear[y])) {
      const a = acc[code] || (acc[code] = { n: 0, approved: 0, net: 0 });
      a.n += o.n; a.approved += o.approved; a.net += o.net;
    }
    cumulative[y] = JSON.parse(JSON.stringify(acc));
  }

  for (const d of Object.values(DATA.districts)) {
    d.pending = APPS.records.filter(r => r.c === d.code && r.s === "pending").length;
  }
}

const cum = code => (cumulative[state.year] || {})[code] || { n: 0, approved: 0, net: 0 };
const nationalCum = () => Object.values(cumulative[state.year] || {})
  .reduce((a, o) => ({ n: a.n + o.n, approved: a.approved + o.approved, net: a.net + o.net }),
          { n: 0, approved: 0, net: 0 });

/* ---------------- init ---------------- */

function init() {
  buildMetricSelect();
  buildOverlays();
  buildSlider();
  setupMap();
  wireControls();
  render();
}

function buildMetricSelect() {
  $("metric").innerHTML = Object.entries(METRICS)
    .map(([k, m]) => `<option value="${k}">${esc(m.label)}</option>`).join("");
  $("metric").value = state.metric;
  $("metric").onchange = () => { state.metric = $("metric").value; render(); };
}

function buildOverlays() {
  $("overlays").innerHTML = OVERLAYS.map(o =>
    `<button class="chip ${state.overlays[o.id] ? "on" : ""}" data-ov="${o.id}"
       style="--sw:${o.color()}"><i class="sw"></i>${esc(o.label)}</button>`).join("");
  d3.selectAll("#overlays button").on("click", function () {
    const id = this.dataset.ov;
    state.overlays[id] = !state.overlays[id];
    d3.select(this).classed("on", state.overlays[id]);
    render();
  });
}

function buildSlider() {
  const s = $("year");
  s.min = YEARS[0]; s.max = YEARS[YEARS.length - 1]; s.value = state.year;
  $("ticks").innerHTML = [YEARS[0], YEARS[Math.floor(YEARS.length / 2)],
                          YEARS[YEARS.length - 1]].map(y => `<span>${y}</span>`).join("");
  s.oninput = () => { setYear(+s.value); };
  updateSliderFill();
}

function updateSliderFill() {
  const s = $("year");
  const pct = (state.year - +s.min) / (+s.max - +s.min) * 100;
  s.style.setProperty("--pct", pct + "%");
  $("yearlabel").textContent = state.year;
}

function setYear(y) {
  state.year = y;
  $("year").value = y;
  updateSliderFill();
  render();
  if (state.selected) renderPanel();
}

/* ---------------- headline figures ---------------- */

// The register carries a first-recorded year per location, from a charity
// registration or a planning approval. Neither is an opening date -- a
// congregation often registers years after it starts meeting, and an approval
// is a decision rather than a building -- but both are documentary evidence
// that a mosque was there by then, which is the most that can honestly be said.
//
// Locations with no dated record at all (OpenStreetMap has no dates) are
// counted in every year: nothing is known about when they appeared, and
// dropping them would understate the past far more than keeping them overstates
// it. So this is today's estate minus what is known to have arrived since, and
// it is labelled as an estimate whenever it is not the present day.
function knownBy(year) {
  let n = 0;
  for (const p of MOSQUES.points) {
    const since = p[4] || 0;
    if (!since || since <= year) n++;
  }
  return n;
}

const isPresent = () => state.year >= YEARS[YEARS.length - 1];

function renderStats() {
  const nat = nationalCum();
  const pending = APPS.records.filter(r => r.s === "pending").length;
  const thisYear = Object.values(byYear[state.year] || {}).reduce((a, o) => a + o.n, 0);

  const stat = (o) => `
    <div class="stat">
      <p class="q">${o.sw ? `<span class="swatch" style="background:${o.sw}"></span>` : ""}
        <span class="q-full">${o.q}</span><span class="q-short">${o.short}</span></p>
      <div class="v num">${o.v}</div>
      <p class="n"><span class="n-full">${o.nfull}</span><span class="n-live">${o.nlive}</span></p>
    </div>`;

  $("stats").innerHTML =
    stat({
      sw: css("--mosque"), q: "How many mosques are there?", short: "Mosques",
      v: fmt(knownBy(state.year)) + (isPresent() ? "" : ' <i class="est">est.</i>'),
      nfull: "", nlive: '<a class="methodlink" href="method.html">See Sources &amp; method &rarr;</a>',
    }) +
    stat({
      q: "How has that changed?", short: "Net change",
      v: `${nat.net > 0 ? "+" : ""}${fmt(nat.net)}`,
      nfull: "net mosques approved in planning, ",
      nlive: `${FIRST_YEAR}–${state.year}`,
    }) +
    stat({
      sw: css("--accent"), q: "What is in planning now?", short: "In planning",
      v: fmt(pending),
      nfull: "awaiting a decision · ",
      nlive: `${fmt(thisYear)} applications in ${state.year}`,
    });
}

/* ---------------- map ---------------- */

function setupMap() {
  svg = d3.select("#map");
  canvas = $("dots"); ctx = canvas.getContext("2d");
  gMap = svg.append("g");
  projection = d3.geoMercator(); path = d3.geoPath(projection);

  gMap.selectAll("path").data(GEO.features).join("path")
    .attr("class", "district")
    .attr("data-code", f => f.properties.LAD24CD)
    .on("click", (e, f) => select(f.properties.LAD24CD))
    .append("title");

  const zoom = d3.zoom().scaleExtent([1, 20]).on("zoom", e => {
    state.transform = e.transform;
    gMap.attr("transform", e.transform);
    drawOverlays();
  });
  svg.call(zoom); svg.node().__zoom__ = zoom;
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
  projection.fitExtent([[14, 14], [w - 14, h - 14]], GEO);
  if (gMap) gMap.selectAll("path.district").attr("d", path);
}

function ramp() {
  return [0, 1, 2, 3, 4, 5].map(i => css("--ramp-" + i));
}

function scaleFor() {
  const m = METRICS[state.metric];
  const vals = GEO.features.map(f => m.get(DATA.districts[f.properties.LAD24CD]))
    .filter(v => v != null && !Number.isNaN(v));
  if (!vals.length) return null;
  if (m.diverging) {
    const lim = d3.max(vals.map(Math.abs)) || 1;
    return d3.scaleDiverging(d3.interpolateRgbBasis([css("--down"), css("--land"), css("--up")]))
             .domain([-lim, 0, lim]);
  }
  // Counts here are heavily long-tailed — most districts have a handful of
  // mosques and a few have dozens. A linear ramp leaves the great majority
  // indistinguishable from the background, so lift the low end with a sqrt
  // scale and clamp the top so one outlier cannot flatten everything else.
  const sorted = vals.slice().sort(d3.ascending);
  const hi = d3.quantile(sorted, 0.97) || d3.max(vals);
  return d3.scaleSequentialSqrt(d3.interpolateRgbBasis(ramp()))
    .domain([d3.min(vals), hi || 1]).clamp(true);
}

function render() {
  colorScale = scaleFor();
  const m = METRICS[state.metric];
  gMap.selectAll("path.district").each(function (f) {
    const d = DATA.districts[f.properties.LAD24CD];
    const v = m.get(d);
    d3.select(this)
      .attr("fill", v == null || Number.isNaN(v) ? css("--land") : colorScale(v))
      .classed("sel", state.selected === d.code);
    this.querySelector("title").textContent =
      `${d.n} — ${v == null ? "no data" : fmt(Math.round(v))} ${m.short}`;
  });
  renderStats();
  drawOverlays();
  renderLegend();
  renderMethod();
}

function project(lon, lat) {
  const t = state.transform, p = projection([lon, lat]);
  return p ? [p[0] * t.k + t.x, p[1] * t.k + t.y] : null;
}

function drawOverlays() {
  const w = $("mapwrap").clientWidth, h = $("mapwrap").clientHeight;
  ctx.clearRect(0, 0, w, h);
  const k = Math.sqrt(state.transform.k);

  if (state.overlays.mosques) {
    const r = Math.max(1.8, 2.3 * k);
    ctx.fillStyle = css("--mosque");
    ctx.globalAlpha = .85;
    for (const [lon, lat, , nsrc, since] of MOSQUES.points) {
      // hide what is known to have arrived after the selected year, so the map
      // and the headline figure agree
      if (since && since > state.year) continue;
      const p = project(lon, lat);
      if (!p || p[0] < -5 || p[1] < -5 || p[0] > w + 5 || p[1] > h + 5) continue;
      // corroborated locations read solid; single-source ones sit back
      ctx.globalAlpha = (nsrc || 1) >= 2 ? .95 : .55;
      ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 6.283); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  if (state.overlays.applications) {
    const s = Math.max(3.4, 4 * k);
    // applications up to and including the selected year, so the slider reads
    // as an accumulating record rather than a single-year flash
    for (const rec of APPS.records) {
      const y = +rec.d.slice(0, 4);
      if (y > state.year || y < FIRST_YEAR) continue;
      const p = project(rec.x, rec.y);
      if (!p || p[0] < -6 || p[1] < -6 || p[0] > w + 6 || p[1] > h + 6) continue;
      ctx.fillStyle = statusColor(rec.s);
      ctx.globalAlpha = y === state.year ? 1 : (rec.q === "high" ? .55 : .3);
      ctx.beginPath();
      ctx.moveTo(p[0], p[1] - s); ctx.lineTo(p[0] + s, p[1]);
      ctx.lineTo(p[0], p[1] + s); ctx.lineTo(p[0] - s, p[1]);
      ctx.closePath(); ctx.fill();
      if (y === state.year) {
        ctx.strokeStyle = css("--surface"); ctx.lineWidth = 1.2; ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
  }
}

function renderLegend() {
  const m = METRICS[state.metric];
  let html = `<div class="title">${esc(m.label)}</div>`;
  if (colorScale) {
    const dom = colorScale.domain();
    const [a, b] = m.diverging ? [dom[0], dom[2]] : dom;
    html += `<div class="ramp">${d3.range(26)
      .map(i => `<i style="background:${colorScale(a + (b - a) * i / 25)}"></i>`).join("")}</div>
      <div class="ticks"><span>${fmt(Math.round(a))}</span><span>${fmt(Math.round(b))}</span></div>`;
  }
  // The long-form keys are hidden on a phone, where the legend was taking a
  // third of the map to explain symbols the chips above already name.
  if (state.overlays.mosques)
    html += `<div class="ln"><span class="kv"><i class="dot" style="background:${css("--mosque")}"></i>
      <span class="l-full">each mosque (${fmt(knownBy(state.year))}) · solid = 2+ sources</span>
      <span class="l-short">mosque</span></span></div>`;
  if (state.overlays.applications)
    html += `<div class="ln">${["approved", "refused", "pending"].map(s =>
      // keep the swatch and its word together, or the line wraps between them
      `<span class="kv"><i class="dia" style="background:${statusColor(s)}"></i>` +
      `<span class="l-full">${STATUS_LABEL[s]}</span>` +
      `<span class="l-short">${STATUS_SHORT[s]}</span></span>`).join("")}</div>`;
  $("legend").innerHTML = html;
}

// One line, not a wall. The caveat that stops the map being misread stays --
// everything else lives on method.html, one click away, where there is room to
// explain it properly.
function renderMethod() {
  const b = DATA.baselines.prov;
  $("method").innerHTML = `
    <span class="m-full">Merged from OpenStreetMap, the charity registers and
    planning records — ${fmt(b.mqc)} of ${fmt(b.mq)} confirmed by more than one
    source.</span>
    <span><b>The slider moves documentary evidence</b>, not opening dates: a
    location appears once a charity register or planning approval records it.</span>
    <a class="methodlink" href="alerts.html">Get planning alerts &rarr;</a>
    <a class="methodlink" href="method.html">Sources &amp; method &rarr;</a>`;
}

/* ---------------- panel ---------------- */

function select(code) {
  state.selected = state.selected === code ? null : code;
  render(); renderPanel();
}

function renderPanel() {
  const panel = $("panel");
  if (!state.selected) { panel.classList.add("empty"); $("panel-body").innerHTML = ""; return; }
  panel.classList.remove("empty");
  const d = DATA.districts[state.selected];
  const c = cum(d.code);

  const recs = APPS.records
    .filter(r => r.c === d.code && +r.d.slice(0, 4) <= state.year)
    .sort((x, y) => y.d.localeCompare(x.d));
  const live = recs.filter(r => r.s === "pending");

  const series = YEARS.map(y => (byYear[y][d.code] || {}).n || 0);
  const maxS = Math.max(1, ...series);
  const spark = series.map((n, i) =>
    `<i class="${YEARS[i] === state.year ? "cur" : ""}" style="height:${n / maxS * 100}%"
        title="${YEARS[i]}: ${n}"></i>`).join("");

  const list = recs.slice(0, 10).map(r => `
    <li class="app">
      <div class="app-top">
        <span class="pill" style="background:${statusColor(r.s)}1f;color:${statusColor(r.s)}">
          ${esc(STATUS_LABEL[r.s] || r.s)}</span>
        <span class="app-date">${esc(r.d)}</span>
      </div>
      <div class="app-kind">${esc(KIND_LABEL[r.k] || r.k)}</div>
      <div class="app-desc">${esc(r.t)}</div>
      ${r.u ? `<a class="app-link" href="${esc(r.u)}" target="_blank" rel="noopener">See the planning record →</a>` : ""}
    </li>`).join("");

  const growth = d.c11 ? d.c - d.c11 : null;
  const cy = d.yr || 2021;   // Scotland counted in 2022, E&W and NI in 2021

  $("panel-body").innerHTML = `
    <div class="p-head">
      <button id="p-close" aria-label="Close">&times;</button>
      <h2>${esc(d.n)}</h2>
      <p class="where">Local authority district</p>
    </div>

    <div class="p-sec">
      <h3>Mosques</h3>
      <div class="figure"><span class="v num">${fmt(d.mq)}</span><span class="u">identified here</span></div>
      <p class="note">${d.ratio != null
        ? `About <strong>${fmt(d.ratio)}</strong> Muslim residents for each one.
           ${fmt(d.mqc)} confirmed by more than one source.`
        : "None identified in this area."}</p>
    </div>

    <div class="p-sec">
      <h3>Change, ${FIRST_YEAR}–${state.year}</h3>
      <div class="figure">
        <span class="v num">${c.net > 0 ? "+" : ""}${fmt(c.net)}</span>
        <span class="u">net mosques approved</span>
      </div>
      <p class="note">From ${fmt(c.approved)} approved decisions out of ${fmt(c.n)} applications.
        Extensions and paperwork are excluded — only new, converted, closed or
        demolished premises change the count.</p>
    </div>

    <div class="p-sec">
      <h3>Applications each year</h3>
      <div class="spark">${spark}</div>
      <div class="spark-ax"><span>${YEARS[0]}</span><span>${YEARS[YEARS.length - 1]}</span></div>
    </div>

    <div class="p-sec">
      <h3>Under way now</h3>
      <div class="figure"><span class="v num">${fmt(live.length)}</span>
        <span class="u">awaiting a decision</span></div>
    </div>

    <div class="p-sec">
      <h3>People</h3>
      <div class="rows">
        <span class="k">Muslim residents, ${cy}</span><span class="v num">${fmt(d.c)}</span>
        ${d.c11 ? `<span class="k">Muslim residents, 2011</span>
          <span class="v num">${fmt(d.c11)}</span>
          <span class="k">Change</span>
          <span class="v num">${growth == null ? "—" : (growth > 0 ? "+" : "") + fmt(growth)}</span>` : ""}
        <span class="k">All residents, ${cy}</span><span class="v num">${fmt(d.pop)}</span>
      </div>
      <div class="caveat">The census asks about religion only once a decade, and
        answering is voluntary — ${d.nrp}% of people here left it blank.${
          d.yr ? ` ${NATION[d.code[0]]} runs its own census: these are ${cy}
          figures, and there is no comparable 2011 series here.` : ""}</div>
    </div>

    ${recs.length ? `<div class="p-sec">
      <h3>Recent applications</h3>
      <ul class="apps">${list}</ul>
      ${recs.length > 10 ? `<p class="note">${recs.length - 10} more up to ${state.year}.</p>` : ""}
    </div>` : ""}`;

  // the panel covers the map on a phone, so tapping the district again to
  // deselect is not reachable -- give it an explicit way out
  $("p-close").onclick = () => select(state.selected);
}

/* ---------------- controls ---------------- */

function wireControls() {
  $("theme").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    buildOverlays();           // chip swatches are theme-coloured
    render();
    if (state.selected) renderPanel();
  };

  $("play").onclick = () => {
    state.playing = !state.playing;
    $("play").classList.toggle("on", state.playing);
    $("play").textContent = state.playing ? "❚❚" : "▶";
    clearInterval(timer);
    if (!state.playing) return;
    if (state.year >= YEARS[YEARS.length - 1]) setYear(YEARS[0]);
    timer = setInterval(() => {
      if (state.year >= YEARS[YEARS.length - 1]) { $("play").click(); return; }
      setYear(state.year + 1);
    }, 700);
  };

  d3.selectAll("#zoomctl button").on("click", function () {
    const z = svg.node().__zoom__;
    if (this.dataset.z === "reset") svg.transition().duration(300).call(z.transform, d3.zoomIdentity);
    else svg.transition().duration(220).call(z.scaleBy, +this.dataset.z);
  });

  document.addEventListener("keydown", e => {
    if (["INPUT", "SELECT"].includes(e.target.tagName)) return;
    if (e.key === "Escape" && state.selected) select(state.selected);
    if (e.key === "ArrowLeft" && state.year > YEARS[0]) setYear(state.year - 1);
    if (e.key === "ArrowRight" && state.year < YEARS[YEARS.length - 1]) setYear(state.year + 1);
  });
}
