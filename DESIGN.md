# Design: Islam in Britain — Interactive Census Map

Status: DRAFT — Phase 1 built (ingestion + map); Phases 2 and 3 not started
Owner: Matthias
Type: Personal project, intended as a public journalism/civic-tech tool
Sibling project: `mer2-scatter-map` (UK Asylum Dispersal Situation Map) — shares
front-end architecture and ingestion utilities, see Related prior work.

## What this is

An interactive census map of the Muslim population of Britain: where it is, how
it has changed since 2011, how old it is, where it was born, and how mosque
provision tracks against it.

Built on the same visual and architectural principles as the asylum dispersal
situation map — dark operational theme, sector shading, time scrubber, slide-in
detail panels, official data separated from live signal — but the underlying
data problem is different. Asylum dispersal is fragmented and contested. Census
data is neither: it is a high-quality decennial count, published in bulk, and
the work is not in obtaining the numbers but in cross-tabulating and rendering
them well.

Scope is one religion for now. The schema underneath stays faith-agnostic
(`faith_category` is a column, not a hardcode), so widening the selector later
is a UI change rather than a re-ingest — but everything specified below is
Muslim-focused, and depth on the one group is the point.

## What it achieves

- Maps the Muslim population of Britain at a granularity and depth that isn't
  currently available in one place. The headline share by local authority
  exists in a dozen places; share cross-tabbed by age, birthplace, ethnicity
  and deprivation, mapped across every GB district with a decade of change,
  does not.
- Answers *why the number moved*, not just *that it moved*. The Muslim
  population of England and Wales grew from roughly 2.7m to 3.9m between 2011
  and 2021. Nearly every serious question about that figure is answered by age
  structure and UK-born share, both of which the census records and neither of
  which is usually mapped.

  The Phase 1 spike already shows this working, and the geography is the
  opposite of the lazy assumption. **51.0% of Muslims in England and Wales are
  UK-born** (against 83.6% of Christians and 92.0% of those with no religion) —
  but the share is *highest* in the districts with the largest, longest-settled
  populations: Hyndburn 67%, Calderdale 66%, Bradford 65%, Kirklees 65%,
  Blackburn with Darwen 64%. It is *lowest* in rural and university districts
  with small, recent, transient populations: Gwynedd 30%, Exeter 31%,
  Cornwall 33%. Where the population is biggest it is majority British-born;
  where it is smallest it is mostly foreign-born. That inversion is the kind of
  finding this tool exists to surface, and it is invisible on a share map alone.
- Maps mosque provision as a capacity ratio — worshippers per mosque, by area —
  which is a genuinely useful planning and journalism number and, as far as I
  can tell, mapped nowhere nationally.
- Converts a decennial data cadence into something live, via a mosque planning
  applications layer, without letting that layer contaminate the census figures.

## Non-goals

- Not a projection tool. Trend lines stop at the last census. Projecting
  forward from two data points across a decade produces a number whose entire
  value is rhetorical, and the census gives no basis for it.
- Not a mosque directory or place-finder. Provision is an aggregate ratio per
  area. Individual buildings appear only where already on a public register,
  and the map does not become a navigable index with photographs, capacity
  estimates, or congregation details.
- Not alerting. No notifications, no per-area subscribe, no
  fastest-changing-town leaderboard.
- Not sub-LAD. **Decided: local authority district is the display geography for
  Phase 1.** MSOA and LSOA are ingested only as a population-weighting surface
  for dot density, never as display units carrying religion figures. Going
  finer is a Phase 4 question, not a Phase 1 one.

## Core design principle: the count is the easy part

Every number in Phase 1 can be downloaded from Nomis in an afternoon. The
design work — and the entire difference between this and the dozens of static
"Muslim population by local authority" tables already online — is in three
things:

**1. Cross-tabs are the product.** Focusing on one religion buys the room to go
deep on it. Share alone is a thin number; share alongside median age, under-16
share, UK-born share, ethnic composition and deprivation decile is an
explanation. The census supports all of these as multivariate outputs. The
single-faith scope is what makes it feasible to render them all in one panel
without the UI collapsing, and that panel is the reason to build the thing.

**2. Denominator discipline.** Count and rate are always shown together, never
rate alone. **Decided: share is calculated against those who answered the
religion question, not all residents.** Religion is the census's only voluntary
question, so "Not answered" is not a religion and excluding it is the more
defensible basis — and because non-response fell between censuses (roughly 7%
in 2011 to roughly 6% in 2021), the answered-only basis also removes a
distortion from the change series that the all-residents basis would carry.

Two consequences, both now measured against the live TS030 data rather than
estimated:

*It raises every share.* National Muslim share for England and Wales is
**6.49% all-residents → 6.91% respondent-basis**. The first is the figure in
every published source; the second is what this map will display.

*The uplift concentrates in exactly the districts that get quoted.* Non-response
ranges from 4.5% (Sunderland) to 10.0% (Kensington and Chelsea), median 5.9% —
it is highest in central London and university cities. Because the uplift scales
with the existing share, the largest divergences land on the highest-share
districts:

| District | All residents | Respondents | Δ |
|---|---|---|---|
| Tower Hamlets | 39.9% | 42.9% | +2.95pp |
| Newham | 34.8% | 37.2% | +2.43pp |
| Luton | 32.9% | 35.1% | +2.13pp |
| Birmingham | 29.9% | 31.8% | +1.94pp |
| Redbridge | 31.3% | 33.2% | +1.89pp |

This is arithmetic, not error, but it means a reader comparing Tower Hamlets
against the widely-cited 39.9% sees a three-point gap and reads it as inflation.
So the dual display is load-bearing rather than a courtesy: **both figures
appear in the panel, and the all-residents figure gets equal or greater visual
prominence**, since it is the one that reconciles externally. The respondent
basis drives the map scale and the analysis; the all-residents basis is what the
panel leads with. Non-response rate is itself an exposed, filterable field, so
any district where the two diverge sharply is visible rather than silently
flattering.

**3. Cartography that doesn't lie about area.** A choropleth shades land, and
land is not people. On this dataset that misleads in both directions — sparse
rural LADs read as significant, dense urban ones vanish. Dot density and
population-weighted surfaces fix it, and are specified as first-class render
modes rather than a nice-to-have. This is the single biggest visual quality
decision in the project, and it matters *more* now that LAD is the display
unit, since LADs vary enormously in physical size.

The all-population baseline is carried alongside every metric — national and
regional averages for the same measure — because a rate is uninterpretable
without one. That is interpretive necessity, not scope creep: "median age 27"
means nothing until it sits next to "40."

---

## Navigation model: how three phases share one screen

The three phases are three *subjects*, and they differ on every axis that
matters:

| | Subject | Geometry | Time | Reliability |
|---|---|---|---|---|
| Phase 1 | people | district areas | decennial | near-complete |
| Phase 2 | buildings | points | no clean series | undercounts, unevenly |
| Phase 3 | events | points | continuous | flaky feed, fuzzy text |

Adding provision and activity metrics to the Phase 1 metric list would not just
crowd it, it would be a category error: "Muslims per mosque" is not an
alternative to "Median age". So the UI is organised around **lenses**.

- **Lens** (People / Provision / Activity) reconfigures the metric list, which
  filter group is open, the time axis, and the default panel tab. It swaps the
  workspace rather than adding to it, so the visible control count stays flat.
- **Selection and filters persist across lenses.** Filter to districts above 20%
  share in People, switch to Provision, and the filter still applies to the same
  selected district. That persistence is what makes this one tool instead of
  three, and it is what makes cross-subject questions answerable.
- **Point data are overlays, not lens-exclusive.** Mosques and applications
  toggle independently in *any* lens, following the asylum map's marker
  precedent — visually distinct, never blended into the choropleth. This matters
  because mosque points over the demographic choropleth is likely the most
  useful single view in the product, and a lens-exclusive design would make it
  impossible to construct.
- **The detail panel is where the subjects actually meet**, tabbed
  Demography / Provision / Activity with a sticky header carrying district name,
  population and Muslim count. The map can only show one variable; the panel can
  show all three for one district.
- **Two time axes, deliberately not unified.** Census years for People and
  Provision, a rolling month window for Activity. One scrubber that means
  "census year" sometimes and "month" other times is worse than two controls.

Lenses without data ship visible but inert, with an empty state naming the
source that will fill them — the structure gets proven before the data lands.

### Reliability has to be visible without more chrome

Census is near-complete; mosque registers undercount unevenly; planning
classification is fuzzy. Rather than a second legend, one reused convention: a
hatch on any choropleth derived from an incomplete register, and a source-tier
chip (`register` / `OSM` / `directory`) on panel figures.

### There is no reliable mosque stock time series

Registers do not publish clean historical snapshots, so a count difference
between two register pulls would mostly measure changes in *registration
behaviour*. What is honestly measurable is flow: planning outcomes over time.
"Change" in the Provision lens is therefore cumulative planning outcomes,
labelled as such — never a stock delta presented as one.

---

## Phase 1 — Verified Census Map

**Goal:** A working map on census data alone, England, Wales and Scotland at
local authority district, 2011 → 2021 scrubber, with the full cross-tab panel.
Ships as something you'd show a journalist.

### 1. Data pipeline

Nomis dataset IDs below are **verified against the live API**, including
geography availability at LAD.

- **ONS Census 2021, England & Wales** — table **TS030** (religion),
  Nomis `NM_2049_1`. Available at `TYPE154` (2022 LA districts) and `TYPE424`
  (district/unitary as of April 2023), plus every level down to OA.
- **Cross-tabs, 2021** — the **RM\*** multivariate series, all confirmed
  available at LAD and below:
  - `NM_2218_1` — **RM118** Religion by age
  - `NM_2131_1` — **RM031** Ethnic group by religion
  - `NM_2123_1` — **RM023** Economic activity status by religion
  - `NM_2154_1` — **RM054** Highest level of qualification by religion
  - `NM_2192_1` — **RM092** NS-SEC by religion

  This is richer than assumed when the doc was drafted — the cross-tabs are not
  the constraint.
- **Age comes from the custom API, not RM118.** RM118 bands age into 9
  categories; the custom-dataset API serves `resident_age_23a` at the same
  coverage (317/318 districts) with an exact break at 15/16. So **under-16 share
  is exact** and **median age is interpolated within the containing band** —
  close to, but not identical to, ONS's own median, and labelled as such in the
  output. Single-year age (`resident_age_101a`) is rejected on *row count*
  rather than disclosure, so it would need per-area batching; not worth it for a
  median. Verified nationally: Muslim median **27.8** and 31.1% under 16,
  against Christian 51.7 / 14.0% and No religion 32.9 / 21.7%.
- **Country of birth × religion — resolved via the custom-dataset API.** The
  2021 RM series has no equivalent to 2011's `DC2207EW`, and the standard 2021
  country-of-birth tables (`TS004`, `RM011`) do not cross by religion. The ONS
  **custom dataset API** does serve it:

  ```
  https://api.beta.ons.gov.uk/v1/population-types/UR/census-observations
    ?area-type=ltla23&dimensions=religion_tb,country_of_birth_8a
  ```

  Granularity is the whole question, and the limit was established empirically
  rather than guessed — blocked districts out of 318:

  | Country-of-birth variant | Blocked | Usable |
  |---|---|---|
  | `country_of_birth_3a` (UK / non-UK) | 1 | 317 |
  | `country_of_birth_8a` (world regions) | 1 | **317** |
  | `country_of_birth_13a` | 169 | 149 |
  | `country_of_birth_60a` | 258 | 60 |

  So the project gets the **8-category world-region breakdown**, not merely the
  UK/non-UK binary originally scoped — richer than planned, at no cost. The one
  blocked district is the Isles of Scilly, already suppressed on population
  grounds. Implemented in `ingest/fetch_religion_cob.py`.

  Note `country_of_birth_3a` and `8a` are *categorisations* of the base variable
  and do not appear in the `/dimensions?q=` search results — only the 60- and
  190-category versions do. Query `/dimensions/<id>/categorisations` to find the
  coarser variants, or the API will look far more restrictive than it is.
- **Census 2011, England & Wales** — table **KS209EW**, Nomis `NM_616_1`, for
  the change series.
- **Scotland's Census 2022** (National Records of Scotland) — religion released
  separately, on a different reference year. Rendered on its own year rather
  than folded into a fake common 2021 snapshot.
- **Northern Ireland** — out of scope. NISRA asks both current religion and
  religion brought up in, on a category set built around the
  Catholic/Protestant denominational split; it is not comparable to the GB
  question and merging it would be wrong rather than merely awkward. "Britain"
  in the title is deliberate.
- **Boundaries and the 2011 series** — ONS Open Geography Portal, generalised
  LAD. Choosing LAD removes the 2011→2021 MSOA/LSOA split-and-merge lookup
  entirely, but it does **not** remove boundary work: Nomis serves TS030 on
  April-2023 boundaries and `KS209EW` only on **pre-April-2015** boundaries, so
  the change series has to be reconciled across local government
  reorganisations (Dorset/BCP and Suffolk 2019, Buckinghamshire 2020,
  Northamptonshire 2021, Cumbria/North Yorkshire/Somerset 2023).

  Every change in that window is a merge into a unitary or a straight recode —
  no splits — so reconciliation is a sum over successors with no apportionment
  and no estimation. The map comes from `mer2-scatter-map`'s `LGR_SUCCESSORS`
  (in `ingest/fetch_support_data.py`, *not* `la_match.py`, which is free-text
  name matching for a different purpose); it is copied here as `ingest/lgr.py`.
  41 abolished codes map onto 318 districts, and the reconciled 2011 population
  comes to 56,075,912 — an exact match to the published England & Wales figure,
  which is the check that nothing was dropped or double-counted.
- **Sub-LAD population, for dot placement only** — LSOA resident population
  (not religion) as the weighting surface for the dot-density render, so dots
  land where people actually live within a district. This makes no claim about
  religion below LAD and must not be reachable through any panel or export.
- **Deprivation** — Index of Multiple Deprivation (MHCLG, LSOA level) and the
  Welsh equivalent, population-weighted up to LAD.
- **Population denominators** — census resident population from the same
  release, so numerator and denominator share a source and a date.

Non-response: religion is the census's **only voluntary question**, and roughly
6% of England and Wales did not answer it. Per the decision in "Denominator
discipline," share is computed against respondents; "Not answered" is carried
as a visible field, never silently redistributed, and the all-residents share
is shown alongside so the figures reconcile with ONS headlines.

Pipeline shape: per-source ingestion → normalization into
`{area_code, area_type, faith_category, measure, value, period, census_authority,
source_ref, confidence: "official"}` → versioned snapshots → map reads current
snapshot, keeps history for trend lines. Same shape as the asylum project, so
`ingest/http_util.py` and the LA-code reconciliation logic carry over directly.

### 2. Metrics

| Metric | Notes |
|---|---|
| Muslim population | Count of residents |
| Share (%) | **Of those who answered**; all-residents share shown alongside |
| Muslims per 10,000 | Same respondent basis |
| Change since 2011 | Percentage points **and** relative %, always shown together — they tell different stories and quoting either alone is the classic distortion |
| Median age | And under-16 share; the primary explanatory variable. RM118 |
| Ethnic composition | Stacked breakdown within the area's Muslim population. RM031 |
| Economic activity, qualifications, NS-SEC | RM023 / RM054 / RM092 |
| Deprivation decile | Population-weighted IMD, LAD level |
| UK-born share | Second explanatory variable. Custom-dataset API, plus world-region origin breakdown |
| Non-response rate | Exposed, not hidden — it is the gap between the two share bases |
| Total population | Plain resident count, always available as a base layer |

Every one of these carries its national and regional baseline in the panel.

### 3. UI/UX

Inherits the asylum map's dark operational theme, monospace numerals, slide-in
detail panel and persistent methodology note. New to this project:

- **Three render modes**, toggleable:
  - **Choropleth** — share or rate at LAD. The conventional view, and the one
    that most needs the other two beside it.
  - **Dot density** — one dot per N Muslim residents, placed within each LAD
    against the LSOA population surface rather than spread uniformly, so dots
    fall where people live. Shows count and concentration at once and cannot be
    misread as "this whole district is X." The honest default, and the render
    that does the most to offset LAD's coarseness.
  - **Kernel density heat map** — continuous surface over the dasymetric
    population grid, for the smooth heat-map read.
- **Filter rail — the sliders.** Dual-handle range filters, cross-filtering,
  areas outside the active ranges dim rather than vanish so spatial context
  survives. One slider each for:
  - Total population
  - Muslim population (count)
  - Share (%) / Muslims per 10,000
  - Change since 2011
  - Median age
  - Deprivation decile
  - Non-response rate
  - *(Phase 2)* Mosque count, and worshippers per mosque

  At LAD the small-numbers problem that would have forced a population floor
  largely dissolves — districts are large enough to carry rates. Two edge cases
  remain and get explicit suppression flags rather than silent rendering: the
  City of London (~8,600 residents) and the Isles of Scilly (~2,000), where
  Muslim counts are small enough that the rate is noise and the disclosure
  control is proportionally significant.
- **Time scrubber** — 2011 → 2021 for England & Wales, Scotland pinned to its
  own 2011 → 2022 pair and labelled as such. Two census points is a thin
  scrubber; it earns its place by animating change-since-2011 as a diverging
  scale rather than replaying a near-identical choropleth.
- **Detail panel** — the cross-tab panel is the centrepiece: count, share, rate,
  change (both forms), age pyramid, UK-born share, ethnic composition bar,
  deprivation, each against its national baseline, with the source table
  reference inline.

### 4. Deliverables

- Nomis / NRS ingestion scripts, normalized dataset, versioned snapshots.
- Boundary prep: LAD vintage pinned, `la_match.py` reused for reorganisations.
- LSOA population surface prepared for dot placement.
- Map front-end: three render modes, filter rail, scrubber, cross-tab panel.
- Methodology page: voluntary question and non-response, the respondent-basis
  denominator decision and why, the two-figure reconciliation with ONS
  headlines, the England&Wales/Scotland year mismatch, and the two suppressed
  districts.

### 5. Success criteria

- Every GB LAD carries a value for every Phase 1 metric for both census years,
  or an explicit suppression flag with a reason.
- National totals reconstructed from the LAD data match the published ONS
  headline figures on the all-residents basis — the check that catches a
  denominator or boundary-reconciliation error, and it should be a test, not a
  one-off eyeball. **It needs a small tolerance, not equality**: summing the 318
  E&W districts gives 59,597,567 against the published 59,597,540, a 27-person
  gap that is disclosure control, not a bug. Assert within a few hundred and
  fail loudly outside that.
- No rate is rendered anywhere without its count and its baseline visible in
  the same view.
- A journalist can, within two minutes, correctly state that the religion
  question is voluntary, see which denominator is in use, and find the table
  reference for any number they click.

---

## Phase 2 — Mosque Provision Layer

**Goal:** Mosque counts and the derived provision ratio.

### 1. Sources

- **Certified places of worship register** — the official list maintained under
  the Places of Worship Registration Act 1855, covering buildings certified and
  those additionally registered for marriages. Structured, official, records
  denomination. It **undercounts**: certification is voluntary, and premises in
  converted or shared buildings frequently never register. The undercount is
  real and must be stated wherever a ratio derived from it appears.
- **Charity Commission register** — religious charities by area; independent
  second count and useful cross-reference.
- **OpenStreetMap** — `amenity=place_of_worship` + `religion=muslim`. Best
  practical coverage, crowd-sourced, uneven by region. Second tier, tagged.
- **Community directories** — the established UK mosque directories are the
  most complete source in existence for this specific question, and materially
  better than the official register. Non-official, third tier, always cited to
  source, never blended into an "official" count.

Tiering follows the asylum map's model: official register → auto-publish with
citation; OSM and directories → tagged and shown, never merged into the
official figure. Where the tiers disagree — and they will, substantially — the
panel shows the range rather than picking a winner.

### 2. Derived metric

`provision_ratio = muslim_population / mosques_in_area`

Ships with a stated source tier and confidence range, and areas below a
threshold mosque count show raw counts instead of a ratio. Because the
denominator is the weakest data in the project, the ratio is presented as a
range across source tiers by default, not a point estimate.

### 3. Success criteria

- Mosque counts at LAD level nationally, from at least two independent tiers.
- Every count traces to a named source tier; the tier is visible in the panel.
- No provision ratio rendered as a single number without its range.

---

## Phase 3 — Live Reports: Mosque Planning Applications

**Goal:** The live layer — planning applications concerning mosques.

### 1. Ingestion

- **PlanIt (planit.org.uk)** — aggregates planning applications across most UK
  local planning authorities and exposes an API. The practical national route.
  Per-LPA portal scraping (Idox, Northgate, Arcus; ~330 authorities in England
  alone) is the fallback for gaps.
- **planning.data.gov.uk** — the government platform; improving, worth
  ingesting alongside for the authorities it covers well.
- **Filtering** — use class is the reliable first hook: **F1(f)** ("public
  worship or religious instruction") in England post-2020, **D1** for pre-2020
  English records and for Wales, which did not adopt the 2020 English use-class
  reform, plus the Scottish equivalent. Class alone is insufficient, so
  free-text descriptions get keyword-then-LLM classification — the layered
  cheap-rules-first pipeline from `uk-council-spend-nlp` applies almost
  unchanged, including its per-row `confidence` / `method` / `rationale`
  provenance fields.
- Extracted record: `{lpa, area_code, application_type, status, date,
  source_url, classifier_confidence}`.

**Application types are tracked in both directions**: new build, extension,
change of use *to* mosque, change of use *away*, and demolition. Change-of-use
is not a footnote here — a large share of UK mosque applications are conversions
of existing buildings rather than new construction, which is the actual planning
story and the one a new-builds-only feed would miss entirely.

### 2. UI

- Toggleable second layer, visually distinct from the census choropleth —
  markers, following the asylum map's `◆` treatment — so the two can never be
  read as one dataset.
- Marker detail: application reference, LPA, type, status, date, and a link to
  the authority's own planning page.
- Status tracked through to decision, so **refused and withdrawn applications
  stay visible**. A feed showing only live applications overstates; a feed
  showing approvals as buildings overstates further. An application is an
  application until the record says otherwise, and the marker says which.

### 3. Publication gate

Lighter than the asylum project's, because planning applications are public
records rather than social claims — the accuracy risk that motivated that gate
is largely absent. What remains is a duplication-and-classification check:
multi-source aggregation across PlanIt and planning.data.gov.uk will produce
duplicates, and LLM classification will produce false positives on ambiguous
descriptions. Anomalous clusters in a single area get a manual look before
publication, mostly to catch exactly those two failure modes. Decisions logged
in `ingest/review_overrides.json`, same pattern as the sibling project.

### 4. Success criteria

- All five application types demonstrably covered — a reviewer can filter to
  refused change-of-use applications and get results.
- Every marker links to the source planning authority record.
- Duplicate rate across sources measured and under a stated threshold;
  classifier precision spot-checked against a manually labelled sample.

---

## Open questions

**Resolved:** denominator basis is respondents, not all residents. Display
geography is LAD. Cross-tab availability is not a constraint — the RM series
reaches OA. UK-born share is available at LAD via the custom-dataset API, with
a world-region breakdown, and no longer a delivery risk.

- **Join on GSS code, never on name.** Nomis and the custom-dataset API disagree
  on district names for the same areas — Nomis has "Bristol, City of",
  "Herefordshire, County of", "Kingston upon Hull, City of"; the ONS API has the
  short forms. A name join silently drops them and looks like disclosure
  blocking. This bit during the Phase 1 spike and will bite again in Phases 2–3,
  where planning and charity data are name-keyed and have no GSS code at all —
  those need an explicit, tested name→code resolver rather than a dictionary
  built on the fly.
- **LAD vintage** — Nomis offers `TYPE154` (2022 districts) and `TYPE424`
  (April 2023 district/unitary, 318 areas, matching the custom API's `ltla23`).
  `TYPE424`/`ltla23` is the working pair. Confirm `mer2-scatter-map` normalises
  to the same vintage so the two maps overlay.
- **Mosque count source of record.** The official register undercounts and the
  best directory is unofficial. Showing a range is the honest answer but makes
  the provision ratio harder to headline. Alternative: publish counts only for
  Phase 2 and hold the ratio until the sources can be reconciled.
- **Dot density at national scale** in-browser vs. pre-rendered tiles. Affects
  the front-end stack choice more than anything else in this doc.
- **Hosting and attribution** — same question as the asylum project, and
  probably wants the same answer, since the two will be read together.

## Related prior work

- **`mer2-scatter-map`** (this machine) — the built asylum dispersal map. Direct
  parent, and reusable more or less as-is: the D3 choropleth and colour-scale
  code in `web/app.js`, the dark theme in `web/style.css`, the detail panel and
  time scrubber, `ingest/http_util.py`, `ingest/la_match.py` (LA code
  reconciliation across the 2019–2024 reorganisations — needed identically
  here), and the `review_overrides.json` review pattern. The `METRICS` object
  structure generalises straight to the metric table above.
- **`uk-council-spend-nlp`** (this machine) — the layered
  supplier-lookup → rules → LLM → embeddings categorisation pipeline is the
  right shape for classifying free-text planning application descriptions in
  Phase 3.
- **`immigration_data`** (this machine) — UTIAC tribunal decisions dashboard.
  Different domain, same underlying instinct; worth a look for ingestion
  patterns, not data.
