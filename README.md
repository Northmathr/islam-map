# islam-census-map

**Mosques in the United Kingdom** — an interactive map answering three counting
questions:

1. **How many mosques are there, and where?**
2. **How has that changed over time?**
3. **What is in planning now?**

Census population sits underneath as context. Local authority district level,
all four nations. See [DESIGN.md](DESIGN.md) for the full design.

Covering the UK means stitching three censuses together: ONS for England and
Wales (March 2021), NISRA for Northern Ireland (March 2021) and NRS for Scotland
(March **2022**). The reference dates differ by a year for Scotland, so any
UK-wide population total spans two of them and the map says which year each
district is on.

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
- **Scotland**, NRS Census 2022 table `UV205` by council area (32), and
  **Northern Ireland**, NISRA Census 2021 by local government district (11).
  NISRA's headline religion table has no Muslim category at all — it stops at
  "other religions" — so the six-category aggregate is used. Neither has a 2011
  comparison here, so change figures remain England and Wales only. Both
  reconcile against published totals: Scotland 5,439,843 residents / 119,878
  Muslims, Northern Ireland 1,903,177 / 10,871.
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
- **Mosque register** — a merge of three sources, deduplicated at 150 m, giving
  **1,842 distinct locations** across the UK (England 1,682, Scotland 106,
  Wales 49, Northern Ireland 5), of which 607 are corroborated by more than one
  and 1,093 carry a dated record. See "Why not just OpenStreetMap" below.
- **Places of worship**, OpenStreetMap via Overpass — every faith from the same
  query, which is what makes the church comparison possible. 1,336 mosques and
  35,737 churches placed across the UK; 1,314 of the mosques fall in England and
  Wales, which is the figure to compare against the merged register.
- **Mosque charities**, Charity Commission (England & Wales) and OSCR
  (Scotland) — **1,146 matched charities, 1,069 geocoded** via postcodes.io.
  Northern Ireland has no open bulk register, so its mosques rest on OSM and
  planning alone. Matching combines the name, the
  charity's own activity description and its registered classification, because
  name matching alone found only 884 (see "Identifying mosque charities").
  Official and citable by charity number, but the postcode is a *contact*
  address, which for some is a trustee or accountant rather than the building.
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

## Why not just OpenStreetMap

OSM alone reports 1,314 mosques in England and Wales, well short of the ~1,800
the MuslimsInBritain directory lists. Two independent checks, both reproducible from this
repo, show the gap is coverage rather than a bad query — widening the Overpass
query to include relations, `building=mosque` and name matching adds only 55
elements:

| Check | Result |
|---|---|
| Planning applications approved to build or convert a mosque | only **73%** have an OSM mosque within 250 m |
| Mosque charities on the Charity Commission register | only **58%** have an OSM mosque within 300 m |

So OSM holds roughly 60–75% of mosques. Triangulating three sources that miss
different things gives 1,842 locations:

| Sources vouching for a location | n |
|---|---|
| OSM only | 678 |
| Charity register only | 484 |
| Charity register + OSM | 372 |
| All three | 115 |
| OSM + planning | 73 |
| Planning only | 74 |
| Charity register + planning | 47 |

### Identifying mosque charities

Name matching alone does not work. Searching the register for "mosque",
"masjid", "jamia" and similar returns 884 charities and misses hundreds that
register as an association or trust — "Newham North Islamic Association",
"Anjuman-ul-Muslimeen", "Gloucestershire Islamic Trust". Widening the pattern
overshoots in both directions: "Sunninghill Parochial Charities" matches on
"sunni", and "Islamic Medical Association" is not a place of worship.

`fetch_charities.py` combines three signals and records which one caught each
entry:

| Evidence | Test | n |
|---|---|---|
| `name` | Name contains mosque / masjid / musalla. Unambiguous. | 411 |
| `activity` | The charity's own activity text says it runs a mosque. | 173 |
| `inferred` | Islamic name + Religious Activities classification + holds land + not an umbrella body. | 409 |

The activity test deliberately excludes the faith-neutral phrase "place of
worship", which matched churches, synagogues and mandirs by the hundred. The
land flag earns its place: 73% of charities whose name says mosque hold land,
against 33% of the register at large.

Result: **1,066 matched charities, 993 geocoded locations**, against Ayaan's
1,179 for the whole UK. The Charity Commission covers England and Wales only
(Scotland has OSCR, Northern Ireland CCNI), so those are close to consistent.

### Cross-check against published counts

| Source | Scope | Count |
|---|---|---|
| **This register** | UK, all types | **1,842** |
| MuslimsInBritain, "actual masjids" | UK | 1,895 |
| MuslimsInBritain, all premises for worship | UK | 2,187 |
| Ayaan Institute, *Mosques in Britain* (2026) | UK | 1,884 |

Within **2%** of the actual-masjid count, and close nation by nation, which is a
stronger test than a single national total that could hide offsetting errors:

| Nation | This register | MuslimsInBritain (all premises) |
|---|---|---|
| England | 1,682 | 2,031 |
| Scotland | 106 | 102 |
| Wales | 49 | 46 |
| Northern Ireland | 5 | 5 |

Scotland, Wales and Northern Ireland land close even against the wider
all-premises basis. England does not, which is where the missing premises are.

Against every premises where Muslims gather to pray (2,187) the register is
**15% short**, and the missing categories are named: hired halls, dedicated
prayer rooms, chaplaincies and temporary premises, none of which a mapped
building, a registered charity or a planning application reliably captures.

The Ayaan report also exposed a real defect here, since fixed: it identified
**1,179** mosques registered as charities UK-wide, where name matching found only
**884** in England and Wales alone. See "Identifying mosque charities" below.

**There is still no single true number**, and not only because of coverage:
"mosque" is not a fixed category. Purpose-built mosques, converted terraces,
industrial units and university prayer rooms are counted differently by
different sources, and that definitional spread is a real part of the gap
between published estimates.

## Headline figures produced

| | Muslim | Christian | No religion |
|---|---|---|---|
| Share of respondents (E&W, 2021) | 6.91% | — | — |
| Median age (banded) | 27.8 | 51.7 | 32.9 |
| Under 16 | 31.1% | 14.0% | 21.7% |
| UK-born | 51.0% | 83.6% | 92.0% |

Change 2011→2021: 2,706,066 → 3,868,130, up 1,162,064 (+42.9%).

**Provision**, UK: 2,171 Muslims per mosque. The church comparison stays on
England and Wales, where the census religion breakdown behind it exists, and
comes from the same OSM query -- both are undercounts, and the mosque side is no
longer OSM alone, so the two are not like for like.

**Planning**, 1,668 applications since 2000:

| Kind | n |
|---|---|
| Extension / alteration *(does not change the count)* | 444 |
| New build or replacement | 351 |
| Change of use to worship | 314 |
| Other / unclassified | 201 |
| Conditions / amendments *(does not change the count)* | 196 |
| Change of use away from worship | 105 |
| Demolition without replacement | 57 |

1,203 approved, 214 refused, 178 withdrawn, 73 awaiting a decision. Net effect
of approved decisions: **+349 mosques**.

The classifier had a second ordering trap behind the demolition one: "erection
of a single storey extension to the mosque" matches the build rule exactly as
"erection of a mosque" does, so 190 extensions, minarets, roofs and car parks
were counted as new mosques. An addition to a building already a mosque is now
recognised as an extension whatever verb is used, moving the net from +503 to
+349. `fetch_planning.py --reclassify` rebuilds every derived output from the
stored snapshot, so a classifier change never needs a refetch. 1,442 of 1,668 matched the search in
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

**Sources and method live on their own page** (`web/method.html`), not in the
footer. The map carries one line — that it shows today's locations and that the
slider moves the planning record — because that is the caveat that stops it
being misread; everything else is a click away where there is room to explain
it. On a phone the footer sheds even the provenance sentence.

**Mobile layout.** The three headline figures sit three-across rather than
stacked, on short labels, and shed the fixed half of their sub-notes so only the
part that moves with the slider survives. Together with a compressed header,
tools and legend, the map keeps roughly 58% of the viewport instead of being
pushed off the bottom. The detail panel gets a close button, since it covers the
map and tapping the district again is not reachable.

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
