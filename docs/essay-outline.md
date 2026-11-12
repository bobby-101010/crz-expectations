# Essay outline and numbers

Working title: "Write it down first: expectation-driven data engineering".

The essay is the owner's to write. This file holds the outline from the spec (Appendix D) and a table of numbers the essay could cite, each with where it was checked. It contains no draft text.

## Outline

1. **Hook.** Football's analytics revolution began with counting situations before making decisions.
2. **The problem.** "Data-driven" without stated expectations means looking at charts after the fact.
3. **The idea.** Expectations recorded before outcomes, as versioned data in the pipeline. Name it, and why not "priors".
4. **Who writes expectations.** Stakeholders, through elicitation, often with AI help. How this project simulated an expert, and what the engineer checked.
5. **Expectations about the world versus checks on the data.** Why scoring waits on checks.
6. **Grain, through the January 4 trace.** The expectation decides what the data model must keep.
7. **Baselines and comparability.** 13.4% against a modeled No Action case versus 11% against an unstated baseline. Two true numbers that can't be compared directly.
8. **Drivers, not causes.** Locating a gap is engineering. Explaining it needs more.
9. **Honest labels.** Official, derived, prospective, and retrospective expectations, and why a "pending" verdict is a feature.
10. **What it costs and where it breaks.**
11. **How this transfers** to other domains, such as health care or finance.

## Numbers

"Checked" says how each number was confirmed:

- **run**: Claude Code ran the query or job and read the result, on 2026-11-11 or 2026-11-12.
- **computed**: arithmetic on numbers marked run.
- **record**: taken from the elicitation record, where the engineer checked it against the source. Not re-checked since.
- **spec**: stated as verified in the spec, from before Claude Code's sessions. Not re-checked.
- **not checked**: yours to source.

| Section | Number | Value | Checked |
| --- | --- | --- | --- |
| 1 | The football analytics claim | | not checked |
| 2, 10 | Trips loaded, 2023-01 to 2026-09 | 1,066,504,959 | run |
| 2, 10 | Entries rows loaded, 2025-01-05 to 2026-10-31 | 6,894,288 | run; equals the source's count |
| 2, 10 | Months of trip data | 45 | run |
| 4 | Entries in the registry | 13: 1 official, 7 prospective, 1 derived, 4 retrospective | run |
| 4 | Entries by an AI expert | 12 of 13 | run |
| 4 | Facts the engineer checked in the interview | 3: Table 3-2, the October 2026 gas price, the 13.4% projection | record |
| 4 | The reproduction target the check corrected | from +1.03% to +0.82% | record; arithmetic recomputed |
| 5 | Check results in the latest full run | 567: 566 pass, 1 warn, 0 fail | run |
| 5 | Required columns that are ever null | 0 in about 1.07 billion rows | run |
| 5 | Trips ending before they start, November 2025, ride-hail | 12,204, all picked up on November 2 between 1:00 and 2:00 | run |
| 5 | The same for yellow | 1,431 of 1,435 | run |
| 5 | Same-zone trips inside the zone that carry the fee, 2025 | 94.8% (ride-hail 98.1%, yellow 91.4%) | run |
| 6 | Fee trips picked up on January 4, 2025, yellow | 401 | spec |
| 6 | Of those, dropped off after tolling began | 397 | spec |
| 6 | Fee trips dropped off before tolling began | 4 | run |
| 7 | The official projection | 13.4% fewer daily vehicles, Phase 1 toll, against No Action | record |
| 7 | The reported first-year outcome | 11%, 27 million fewer vehicles, baseline not named | spec |
| 7 | Entries rows on a normal day | 10,368 (6 classes, 12 groups, 144 blocks) | run |
| 7 | Entries rows when daylight saving starts and ends | 9,936 and 10,800 | run |
| 7 | Baseline rows | 97,870 | run |
| 7 | Share of ordinary days inside a band built from 7 or 8 values | about 61% | record; the expert's figure, not checked |
| 8 | Trips touching the zone, first year of tolling against the year before | +1.72% | run |
| 8 | Yellow's gap in that entry | +4,637,079 trips | run |
| 8 | Ride-hail's gap in that entry | -3,543,880 trips | run |
| 8 | Lyft's and Uber's gaps, January to September 2025 | +2,058,044 and -2,031,079 trips | run |
| 8 | Largest share of gap seen | +7,483% | run |
| 9 | Verdicts | 5 held, 7 pending, 1 not scoreable | run |
| 9 | Table 3-2 total: target and observed | +0.82% and +0.79% | run |
| 9 | Table 3-2 yellow: target and observed | +16.87% and +16.71% | run |
| 9 | Table 3-2 ride-hail: target and observed | -4.86% and -4.86% | run |
| 9 | Ride-hail trips per yellow trip, first year of tolling | 4.99 | run |
| 9 | The same ratio for calendar 2024 | 5.82 | computed |
| 9 | Yellow trips, 2024 to 2025 | +18.3% | computed |
| 9 | Ride-hail trips, 2024 to 2025 | +1.7% | computed |
| 9 | Share of trips carrying the fee in 2025 | yellow 72%, ride-hail 34% | computed |
| 10 | Full checks run | 3 min 15 s | run |
| 10 | Gold rebuild for 45 months | 6 min 44 s | run |
| 10 | Entries download for 22 months | about 18 min | run |

## Things to keep straight

- The 13.4% and the 11% rest on different baselines. The spec asks the essay to say so.
- The MTA's headline counts add excluded roadways to zone entries. This project's `crz_entries` does not.
- A driver shows where a gap sits. The project never calls one a cause.
- All seven prospective entries were pending on 2026-11-12. If that has changed, the verdicts and the expert's record need re-reading.
