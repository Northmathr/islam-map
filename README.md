# islam-census-map

Interactive census map of the Muslim population of Britain: where it is, how it
has changed since 2011, how old it is, where it was born, and (later) how mosque
provision tracks against it. Local authority district level, England and Wales
so far. See [DESIGN.md](DESIGN.md) for the full design.

**Status:** Phase 1 complete — ingestion and map. Phases 2 (mosque provision) and
3 (planning applications) not started.

## Two things to know before reading the numbers

**Shares are computed against those who answered the religion question**, not
all residents. Religion is the census's only voluntary question and roughly 6%
skipped it. Both bases are in the output, because they differ by enough to
matter — nationally 6.49% (all residents) vs 6.91% (respondents), and the gap is
widest in the highest-share districts (Tower Hamlets 39.9% → 42.9%). Anything
user-facing shows both.

**Join on GSS code, never on name.** Nomis and the ONS custom-dataset API use
different names for the same districts — "Bristol, City of" vs "Bristol",
likewise Herefordshire and Kingston upon Hull. A name join drops them silently
and looks exactly like disclosure blocking.

## Data

- **TS030** religion, 2021, Nomis `NM_2049_1` at `TYPE424` (April 2023
  district/unitary, 318 areas in E&W).
- **KS209EW** religion, 2011, Nomis `NM_616_1`. Only published on pre-April-2015
  boundaries, so it is summed onto 2023 successors via `ingest/lgr.py` before the
  change series is computed. 41 abolished codes; reconciled 2011 population
  matches the published E&W figure exactly.
- **Religion × country of birth**, 2021, via the ONS custom-dataset API. There is
  no standard 2021 table for this (2011 had `DC2207EW`). Disclosure control
  allows the 8-category world-region breakdown at LAD — 317/318 districts, the
  exception being the Isles of Scilly.
- **Religion × age**, 2021, custom-dataset API `resident_age_23a` — 23 bands,
  preferred over Nomis RM118's 9. Under-16 share is exact; median age is
  interpolated within the containing band and labelled as banded-derived.

Disclosure control perturbs individual cells, so reconciliation checks assert a
small tolerance rather than equality — summing the 318 districts gives a 2021
population of 59,597,567 against a published 59,597,540.

## Headline figures produced

| | Muslim | Christian | No religion |
|---|---|---|---|
| Share of respondents (E&W, 2021) | 6.91% | — | — |
| Median age (banded) | 27.8 | 51.7 | 32.9 |
| Under 16 | 31.1% | 14.0% | 21.7% |
| UK-born | 51.0% | 83.6% | 92.0% |

Change 2011→2021: 2,706,066 → 3,868,130, up 1,162,064 (+42.9%).

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

`certifi` is not optional — the system Python here has no usable CA bundle and
every ONS/Nomis fetch fails with `CERTIFICATE_VERIFY_FAILED` without it.

```bash
cd ingest && ../.venv/bin/python fetch_religion.py
```

```bash
cd ingest && ../.venv/bin/python fetch_age.py
```

```bash
cd ingest && ../.venv/bin/python fetch_religion_cob.py
```

Each script prints its reconciliation check and exits non-zero if a national
total drifts outside tolerance.

## Output

Written to `data/`:

| File | Contents |
|---|---|
| `religion_ltla23.csv` | Map feed — counts, both share bases, per-10k, 2011 comparison, change in pp and relative % |
| `religion_ltla23_long.csv` | All faith categories, long format |
| `age_by_religion_ltla23.csv` | Median age and under-16 share per district per faith |
| `religion_cob_ltla23.csv` | Religion × country of birth, 8 world regions |
| `uk_born_share_ltla23.csv` | Derived UK-born share per district per faith |

Rates are suppressed where the population is under 1,000, and for the Isles of
Scilly and City of London, which are too small for a meaningful rate.

## The map

```bash
cd web && python3 -m http.server 8777
```

Then open <http://localhost:8777>. Static files only — no build step.

**Three lenses** — People, Provision, Activity — because the project covers three
subjects that differ in geometry, time axis and reliability. A lens swaps the
metric list, the open filter group, the time axis and the panel tab rather than
adding controls, so the interface does not grow as phases land. Selection and
filters persist across lenses. Provision and Activity are visible but inert
until Phase 2/3 data is ingested; their empty states name the source that will
fill them. Keys `1` / `2` / `3` switch lens.

**Overlays** (mosque points, planning applications) are available in *every*
lens rather than locked to one — mosque points over the demographic choropleth
is the view worth building the whole thing for.

**Three renders**, because a choropleth alone misleads here: it shades land, and
English districts vary enormously in physical size, so sparse rural areas read
as significant and dense urban ones vanish.

- **Choropleth** — the conventional view, kept for familiarity.
- **Dot density** — one dot ≈ 150 people, placed against LSOA
  population-weighted centroids so marks land where people actually live. This
  is the honest default.
- **Heat** — the same surface, smoothed.

Dot placement uses sub-district *population* only. No religion data below
district level is fetched, stored, or shipped; dots are positioned by where
people live and coloured by a district-level figure.

**Filter rail** — dual-handle ranges over population, Muslim population, share,
change since 2011, median age, UK-born share and non-response. Districts outside
the ranges dim rather than vanish, so spatial context survives.

**Scrubber** — 2011 / 2021. Only population and Muslim count/share have a 2011
equivalent; other metrics say so rather than silently showing 2021 data.

**Detail panel** — tabbed Demography / Provision / Activity with a sticky header
so switching tab never loses the district. Demography carries count, both share
bases, non-response, change in both pp and relative terms, median age /
under-16 / UK-born each against its national baseline, ethnic composition of the
district's Muslim population, all religions as a stacked bar, and the source
table for every figure.

## Layout

```
ingest/
  http_util.py   HTTP with certifi (mirrors mer2-scatter-map)
  nomis.py       Nomis bulk tables, verified dataset IDs, paging
  ons_api.py     ONS custom-dataset API — paging, blocked-area reporting
  arcgis.py      ONS Open Geography FeatureServer paging
  lgr.py         Local government reorganisation successor map
  fetch_*.py     One script per source
  build_web_data.py  Merges the CSVs into web/data/districts.json
data/            CSV output
web/             The map — index.html, app.js, style.css, data/
```

Rebuild the whole thing:

```bash
cd ingest && for s in religion age religion_cob ethnicity geography; do ../.venv/bin/python fetch_$s.py; done && ../.venv/bin/python build_web_data.py
```

## Related

- `../mer2-scatter-map` — the UK asylum dispersal situation map. Parent project;
  `http_util.py` and the LGR successor map come from it, and the front-end
  (D3 choropleth, dark theme, time scrubber, detail panels) is the intended base
  for this one.
- `../uk-council-spend-nlp` — layered rules-then-LLM categorisation, the right
  shape for classifying planning application text in Phase 3.
