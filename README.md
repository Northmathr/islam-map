# islam-census-map

**Mosques in England &amp; Wales** — an interactive map answering three counting
questions:

1. **How many mosques are there, and where?**
2. **How has that changed over time?**
3. **What is in planning now?**

Census population sits underneath as context. Local authority district level.
See [DESIGN.md](DESIGN.md) for the full design.

**Status:** Working build, reframed around the three questions above. One map
render, raw counts, a year slider, light and dark themes.

## Two things to know before reading the numbers

**The interface shows raw counts, not shares.** The question is "how many", and
percentage-of-respondents versus percentage-of-all-residents answered a question
nobody was asking while doubling the ways to misread the map. Both bases are
still computed in `data/religion_ltla23.csv` for anyone doing analysis — they
differ by enough to matter (nationally 6.49% vs 6.91%) — they are just not the
product.

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
- **Places of worship**, OpenStreetMap via Overpass — every faith from the same
  query, which is what makes the provision ratio meaningful. **A floor, not a
  register**: 1,336 mosques and 35,737 churches placed, against a commonly cited
  UK mosque estimate nearer 1,800, so coverage is roughly three quarters and the
  undercount is not uniform across faiths. Every row carries `source_tier`.
- **Planning applications**, PlanIt aggregation of local planning authority
  registers — **1,668 applications since 2000 across 162 districts**. Ingested
  to a local snapshot; the map never reads the feed live, because it is not
  reliable enough to sit in the render path. Coverage improves over time, so
  earlier years are thinner as a matter of record-keeping rather than activity —
  the map says so rather than implying a trend.

Points from both are placed into districts by **point-in-polygon on coordinates**
(`ingest/geo.py`), never by the name the source supplies — PlanIt's `area_name`
is the planning authority, which is not always the district.

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

**Provision**, England & Wales: 2,944 Muslims per mosque against 821 Christians
per church. Both from the same OSM query, both undercounts.

**Planning**, 1,668 applications since 2000:

| Kind | n |
|---|---|
| New build or replacement | 541 |
| Change of use to worship | 313 |
| Extension / alteration *(does not change the count)* | 259 |
| Conditions / amendments *(does not change the count)* | 199 |
| Other / unclassified | 191 |
| Change of use away from worship | 108 |
| Demolition without replacement | 57 |

1,203 approved, 214 refused, 178 withdrawn, 73 awaiting a decision. Net effect
of approved decisions: **+503 mosques**. 1,442 of 1,668 matched the search in
the description rather than only the address.

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

```bash
cd ingest && ../.venv/bin/python fetch_mosques.py
```

```bash
cd ingest && ../.venv/bin/python fetch_planning.py
```

Overpass responses are cached under `ingest/.overpass_cache/`, so a run
interrupted by a 504 resumes rather than refetching. Delete it to force a
refresh. Each census script prints its reconciliation check and exits non-zero if a national
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
| `places_of_worship.csv` | Every mapped place of worship with faith, coordinates and source tier |
| `provision_ltla23.csv` | Counts per district per faith |
| `planning_applications.csv` | Every application with kind, status, confidence and link |
| `planning_ltla23.csv` | Per-district planning rollup |

Rates are suppressed where the population is under 1,000, and for the Isles of
Scilly and City of London, which are too small for a meaningful rate.

## The map

```bash
cd web && python3 -m http.server 8777
```

Then open <http://localhost:8777>. Static files only — no build step.

**Three headline figures** across the top answer the three questions directly
and update with the year slider.

**Light and dark themes**, following the system setting and remembered per
browser. Warm paper base, serif headings, one restrained accent — a research
publication rather than an operations console.

**A year slider, 2000–2026**, with a play button. It drives the planning
series: applications that year, and the running total of approved mosque gains.
Arrow keys step a year at a time.

**One render — choropleth.** Dot density and heat were removed along with the
lens switcher: with the scope narrowed to counting mosques, they were options
rather than answers.

**Two overlays**, both on by default: every mapped mosque, and planning
applications coloured by decision. Applications accumulate up to the selected
year, with that year's highlighted.

**Detail panel** — plain-language answers for the selected district: mosques,
residents per mosque, net change, a per-year sparkline, what is awaiting a
decision, and the recent applications with links to the planning record. Muslim
residents for 2011 and 2021 sit at the bottom as context, with the voluntary
nature of the census question stated inline.

## Layout

```
ingest/
  http_util.py   HTTP with certifi (mirrors mer2-scatter-map)
  nomis.py       Nomis bulk tables, verified dataset IDs, paging
  ons_api.py     ONS custom-dataset API — paging, blocked-area reporting
  lgr.py         Local government reorganisation successor map
  geo.py         Point-in-polygon assignment of points to districts
  arcgis.py      ONS Open Geography FeatureServer paging
  fetch_*.py     One script per source
  build_web_data.py  Merges the CSVs into web/data/districts.json
data/            CSV output
web/             The map — index.html, app.js, style.css, data/
```

Rebuild the whole thing:

```bash
cd ingest && for s in religion age religion_cob ethnicity geography mosques planning; do ../.venv/bin/python fetch_$s.py; done && ../.venv/bin/python build_web_data.py
```

## Related

- `../mer2-scatter-map` — the UK asylum dispersal situation map. Parent project;
  `http_util.py` and the LGR successor map come from it, and the front-end
  (D3 choropleth, dark theme, time scrubber, detail panels) is the intended base
  for this one.
- `../uk-council-spend-nlp` — layered rules-then-LLM categorisation, the right
  shape for classifying planning application text in Phase 3.
