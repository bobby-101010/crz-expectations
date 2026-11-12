# Expectation elicitation, November 11, 2026

This is the full record of how the expectations in `expectations/registry.yaml` were produced. It is kept unedited, so anyone can see where each number came from.

## Why it was done this way

The owner is a data engineer, not a transportation analyst. In a real deployment the expectations would come from subject matter experts (SMEs), and the engineer's job is to elicit them, make them machine-readable, and score them automatically. This project simulates that.

- **The expert** is a Claude subagent, prompted to act as a senior transportation analyst. It had web search and did its own research.
- **The engineer** is Claude in the planning chat, acting for the owner. It wrote the briefing, asked the follow-up questions, and checked key facts.
- **The owner** reviewed the resulting entries and approved them by committing the registry.

Every entry is labeled `author: ai_sme` and links to this file. Nothing in the registry claims to be the owner's own forecast.

## Protocol

1. **Briefing.** The expert received the metrics the pipeline can measure, what data had been published as of the interview, the official figures, and the project's own trip totals.
2. **Draft.** The expert proposed expectations, each with an 80% interval, a rationale, and sources.
3. **Challenge.** The engineer checked measurability, windows and arithmetic, then asked follow-up questions.
4. **Lock.** The final numbers went into the registry, which is append-only from then on. A revision needs a new entry.

The rule against leakage: a forward-looking (`prospective`) window must not be published when the expectation is recorded. The expert was told to stop if it found such data, and it reported finding none.

## The engineer's checks

| Claim | Checked against | Result |
| --- | --- | --- |
| MTA Table 3-2: average daily trips starting or ending in the zone, Jan–Sep 2024 against 2025 (308,110 → 312,428; yellow 79,963 → 93,794; ride-hail 225,998 → 215,809) | [MTA First Evaluation Report, January 2026](https://www.mta.info/document/195631) | Confirmed. The total includes industries this pipeline doesn't load, so the reproduction target was corrected from +1.03% to +0.82%. |
| New York's average gas price was $4.48 on October 1, 2026, $1.28 above a year earlier | [FingerLakes1, citing AAA, October 2, 2026](https://www.fingerlakes1.com/2026/10/02/new-york-gas-averages-4-48-as-national-prices-ease-after-record-september/) | Confirmed |
| Reevaluation 2 projects a 13.4% daily vehicle reduction for the Phase 1 toll | [MTA Reevaluation 2, Table 2.2](https://www.mta.info/document/158191) | Confirmed. The document is dated November 2024, with no day given. |

The expert's other sources were not checked one by one. They support its reasoning, not the numbers the pipeline scores.

## Decisions the engineer made when building the registry

- **R1 (all services)** uses only the yellow and ride-hail target, because those are the only services the pipeline loads.
- **Expectation 8** uses the 42.8 to 85.8 range. That assumes the baseline band is computed with Spark's exact `percentile`, which interpolates linearly. The spec now says so.
- **The October ratio (5b)** uses the expert's preferred form: `change_vs_period` on the ratio, +2.0 to +16.5. The spec now defines `change_vs_period` for ratio metrics as the window ratio divided by the comparison ratio, minus 1.
- **Drivers the pipeline can't slice by** were dropped, with a note: day of week, and any dimension of a ratio metric.
- **Vehicle classes** use canonical labels (`cars_pickups_vans`, `tlc_taxi_fhv`). Their mapping to the source must be one-to-one and must fail on any label it can't map, as the expert asked.
- **Calibration** of the expert is measured only on `prospective` entries. That leaves out Expectations 4 and 5 and R1 to R3, as the expert asked.

---

## Transcript


### Engineer (planning chat, for the owner), message 1

Thank you for making time for this. I'm the data engineer on a pipeline that tracks New York City's congestion pricing program, and I need your expectations as the subject matter expert.

## Your role

Act as a senior transportation analyst at a New York City policy research group. You have studied cordon pricing in London, Stockholm, and Singapore, and you know Manhattan's traffic patterns, the taxi and for-hire markets, and the MTA's and the Taxi and Limousine Commission's data well. I'm the engineer. My job is to turn your expectations into something the pipeline can check automatically. Yours is to say what should happen, by how much, and why.

## What an expectation is here

An expectation is written down before the data for its window is available, then scored automatically once the data arrives. Each one needs:

1. **Statement.** One sentence a non-specialist can read.
2. **Metric,** chosen from the list below, with optional filters on its dimensions.
3. **Comparison type,** one of three:
   - `change_vs_period`: percent change of the metric's total over the window against a comparison window. By default the comparison window is the same window shifted back 364 days, which keeps weekdays aligned. You can name a different one.
   - `within_baseline`: the percent of days in the window whose daily value falls inside that day's normal band. The band is the 10th to 90th percentile of the same weekday over the previous 8 weeks, holidays excluded.
   - `value_range`: the daily mean of the metric over the window, or the window ratio for a ratio metric, in the metric's own units.
4. **Window:** start and end dates, inclusive, plus the comparison window if it differs from the default.
5. **Expected range:** low and high, in the comparison's unit. Make it an honest 80% interval. If the result falls outside it, you should be surprised about one time in five. Keep it narrow enough that a miss tells us something.
6. **Rationale:** your reasoning, including the base rates or analogies you used and what would surprise you.
7. **Sources** for any facts you cite.
8. **Drivers to examine,** optional: which dimensions to break a gap down by.

## Metrics the pipeline can measure

| Metric | Meaning | Dimensions you can filter or slice by |
| --- | --- | --- |
| `crz_entries` | Daily vehicle entries into the Congestion Relief Zone (Manhattan at or below 60th Street), from the MTA's 10-minute entry counts. Starts January 5, 2025, so no pre-launch data. | `vehicle_class` (cars, pickups and vans; small trucks; large trucks; buses; motorcycles; TLC taxis and for-hire vehicles), `detection_group` (entry point, such as Lincoln Tunnel or Queensboro Bridge), `time_period` (peak, overnight) |
| `excluded_roadway_entries` | Daily entries on excluded roadways (FDR Drive, West Side Highway, Hugh L. Carey Tunnel to West Side Highway, and so on) | same as above |
| `tlc_trips` | Daily trips from TLC trip records | `service` (`yellow` taxis, `fhvhv` = Uber and Lyft), `operator_code` (HV0003 Uber, HV0005 Lyft), `zone_relation` (both ends in the zone, pickup only, dropoff only, neither), `pickup_hour` |
| `tlc_cbd_touch_trips` | Daily TLC trips with pickup or dropoff in a zone inside the Congestion Relief Zone | same as `tlc_trips` |
| `tlc_fee_trips` | Daily TLC trips that paid the congestion fee | same as `tlc_trips` |
| `fhvhv_per_yellow` | Ratio of ride-hail trips to yellow taxi trips | none |

## Data availability (today is Wednesday, November 11, 2026)

- **TLC trip records** are loaded from January 2023 through September 2026. October 2026 publishes around December, about two months late.
- **MTA entries** are published weekly. Public analyses use data through mid to late October 2026. Nothing for November 2026 is published as far as I know.

## Briefing: what we already know

- **Official projection.** The MTA's Reevaluation 2 (November 2024), Table 2.2, projected a 13.4% daily reduction in vehicles entering the zone under the $9 Phase 1 toll, relative to a modeled No Action case with 2023 as the analysis year.
- **Reported first year.** The Governor's release of January 5, 2026 reported 27 million fewer vehicles entering the zone in year one, an 11% reduction. The release does not state the baseline.
- **Year two versus year one.** A secondary analysis of the MTA entries data (recordinglaw.com, October 26, 2026) compared January 5 to October 17 in 2026 and 2025:
  - entries were 4.1% lower in 2026 (135,553,926 against 141,280,288);
  - from March 1 to October 17 they were 3.0% lower;
  - cars, pickups and vans fell 7.4%, while taxis and for-hire vehicles rose 1.6%.
- **Monthly totals from the same analysis:** October 2025 had 15,746,928 entries, and September 2026 had 14,416,403.
- **TLC trips in our own data,** total trips with the share that paid the fee:

| Service | 2023 | 2024 | 2025 | 2026 (Jan–Aug) |
| --- | --- | --- | --- | --- |
| Yellow | 38.3M | 41.2M | 48.7M (72% paid the fee) | 29.7M (72% paid the fee) |
| Ride-hail | 232.5M | 239.5M | 243.6M (34% paid the fee) | 168.2M (32% paid the fee) |

  Yellow rose 18.3% from 2024 to 2025 while ride-hail rose 1.7%. Ride-hail trips per yellow trip were 6.07 in 2023, 5.82 in 2024, 5.00 in 2025, and 5.66 for January to August 2026. Monthly averages: yellow 4.06M in 2025 against 3.71M in January to August 2026, and ride-hail 20.30M against 21.02M. Seasonality makes the partial-year comparison rough.

## What I need from you

Propose 5 to 8 expectations. Include these:

1. **Required, prospective:** `crz_entries`, all vehicles, Sunday November 8 to Saturday November 14, 2026, against Sunday November 9 to Saturday November 15, 2025. The owner chose this window. Both weeks contain Veterans Day.
2. **Required, prospective:** at least one about TLC October 2026, which is not yet published.
3. **Derived:** your translation of the official 13.4% projection onto a metric we can measure. TLC trips touching the zone in the first 52 weeks of tolling (January 5, 2025 to January 3, 2026) against the same weeks a year earlier is the obvious candidate. Note that this window's data has already been loaded, and I've shown you yearly totals, so say how that affects the expectation's standing.
4. **Retrospective:** something about the ride-hail to yellow ratio, which you now know shifted in 2025.

Beyond those, add whatever you think matters most: by vehicle class, by time period, a `within_baseline` check for an upcoming week, and so on. Any window you call prospective must be one whose data you have not seen and that is not yet published.

## Ground rules

- You may research context on the web: holidays, events, weather, policy changes, published analyses. Cite what you use.
- If you come across published data for any of the prospective windows above, stop and tell me rather than using it.
- Be honest about uncertainty. A wide range with a clear reason is better than false precision.
- Separately, list any expectation you would want that these metrics can't express. I'll take it back as a request.

## Format

For each expectation, give one block with these fields: statement, origin (prospective, derived, or retrospective), metric, filters, comparison, window, comparison window (or "default"), expected low, expected high, unit, confidence note, rationale, sources, and drivers to examine. End with a short list of what you would watch, and the expectations you couldn't express.


### Expert (AI subagent), message 1

I wrote eight expectations. The required week (Expectation 1) centers on entries about 4% lower than the matching week of 2025, a little steeper than the −3.0% average for March to October. My main reason is a factor your briefing doesn't mention: fall 2026 gas prices are about 40% higher than a year earlier.

I found no published data for any prospective window here: the Nov 8–14 week, Oct 2026 TLC, or the November weeks. The MTA entries analysis I used ends October 17, 2026, and I did not open any real-time traffic reports for Nov 8–11. I tried to download TLC's monthly aggregate file to get monthly 2025 baselines, but this session's network rules blocked it, so I never saw its contents. The October TLC ranges therefore rest on reconstructed baselines (explained in Expectation 2), and they are the softest numbers here.

## Context from research that moved my numbers

- **Gas prices.** New York averaged $4.48 a gallon on Oct 1, 2026, against about $3.20 a year earlier, after a record September ([FingerLakes1/AAA](https://www.fingerlakes1.com/2026/10/02/new-york-gas-averages-4-48-as-national-prices-ease-after-record-september/)). The recordinglaw analysis also lists January 2026 fare and toll increases, and storms in Jan–Feb 2026 including a Feb 22–23 travel ban ([recordinglaw](https://www.recordinglaw.com/data-stories/nyc-congestion-pricing-traffic-data/)).
- **The decline is widening.** The MTA's First Evaluation Report gives average daily entries for the zone plus excluded roadways: 570,357 for Sep 2025 ([MTA](https://www.mta.info/document/195631)). In May and Oct 2025, the zone-only total was 88.4–88.8% of that figure. Applying that share puts Sep 2025 zone entries at about 15.13M–15.20M, so Sep 2026 (14,416,403) is about −4.7% to −5.2%. Both Septembers have the same weekday mix. May 2026 against May 2025 is −3.6% raw, or about −3.0% after adjusting for one fewer weekday.
- **The MTA's headline counts excluded roadways too.** Its monthly figures, and so the 11% claim, are zone plus excluded roadways, not `crz_entries` alone.
- **The derived window's answer is largely published.** The same report's Table 3-2 shows TLC trips that start or end in the zone rose 1.4% for Jan–Sep 2025 against 2024, in average daily trips (308,110 to 312,428). Ride-hail fell 4.5% and yellow rose 17.3%.
- **Why yellow surged in 2025.** Cabs came back into service (more than 1,000 medallions) and Uber and Curb dispatched more of them ([AutoMarketplace](https://automarketplace.substack.com/p/nyc-tlc-market-update-yellow-cab)). TLC's figure is taxi trips up 16% ([TLC testimony, 3/17/26](https://www.nyc.gov/assets/tlc/downloads/pdf/testimony_preliminary_budget_3_17_26.pdf)).
- **An unlicensed competitor.** Empower, which operates without a TLC license, priced about 30% below Uber and Lyft in 2026 ([Axios](https://www.axios.com/2026/05/20/new-york-rideshare-battle)). Its trips never appear in TLC records.
- **The comparison week in 2025** contained the end of the federal shutdown, with FAA flight cuts of 2–5% at New York airports ([ABC7](https://abc7ny.com/live-updates/government-shutdown-updates-flights-canceled-when-will-snap-benefits-resume-more/18137769/)). Veterans Day 2025 brought the season's first snowflakes and a cold snap ([ABC7](https://abc7ny.com/post/nyc-snow-first-snowflakes-season-fall-new-york-jersey/18143118/)).

---

## Expectation 1: Veterans Day week entries (required)

- **Statement:** In the week of Nov 8–14, 2026, about 4% fewer vehicles will enter the Congestion Relief Zone than in the matching week of 2025.
- **Origin:** prospective
- **Metric:** `crz_entries`
- **Filters:** none (all vehicles)
- **Comparison:** `change_vs_period`
- **Window:** 2026-11-08 to 2026-11-14
- **Comparison window:** default (2025-11-09 to 2025-11-15)
- **Expected low:** −7.5
- **Expected high:** −1.0
- **Unit:** % change
- **Confidence note:**
  - I give it about an 80% chance of landing inside the range, centered on −4.3%.
  - Below −7.5%: a storm in 2026, or a counting outage on the MTA side.
  - Above −1.0%: gas prices falling back sharply, or an unusual 2025 week.
  - The window is partly over, but I used no information from those days.
- **Rationale:**
  - The year-two gap was −3.0% from March to mid-October, widening to about −5% in September as gas peaked. Gas has eased since, but is still about 30–40% above last year, so I center between the two.
  - Both weeks contain Veterans Day on a weekday, Tuesday in 2025 and Wednesday in 2026. A Tuesday holiday tempts people to take Monday off, which lowers the 2025 week and adds about 0.3–0.5 points to 2026.
  - The 2025 week's shutdown, flight cuts and cold snap matter little for vehicles entering below 60th Street.
  - Weekly YoY noise of about 2 points, plus uncertainty in the trend, sets the width.
- **Sources:** [recordinglaw](https://www.recordinglaw.com/data-stories/nyc-congestion-pricing-traffic-data/); [MTA First Evaluation Report](https://www.mta.info/document/195631); [FingerLakes1/AAA gas](https://www.fingerlakes1.com/2026/10/02/new-york-gas-averages-4-48-as-national-prices-ease-after-record-september/); [ABC7 shutdown](https://abc7ny.com/live-updates/government-shutdown-updates-flights-canceled-when-will-snap-benefits-resume-more/18137769/); [ABC7 snow](https://abc7ny.com/post/nyc-snow-first-snowflakes-season-fall-new-york-jersey/18143118/)
- **Drivers to examine:**
  - `vehicle_class`: cars should carry the decline.
  - `detection_group`: the Lincoln Tunnel was −11.8% year to date, so check for construction or closures there.
  - Day of week: Monday Nov 10, 2025 against Monday Nov 9, 2026.
  - `time_period`

## Expectation 2: Yellow taxi trips in October (required TLC)

- **Statement:** Yellow taxis will make about 5% fewer trips in October 2026 than in October 2025.
- **Origin:** prospective
- **Metric:** `tlc_trips`
- **Filters:** `service = yellow`
- **Comparison:** `change_vs_period`
- **Window:** 2026-10-01 to 2026-10-31
- **Comparison window:** default (2025-10-02 to 2025-11-01)
- **Expected low:** −11.0
- **Expected high:** +1.0
- **Unit:** % change
- **Confidence note:**
  - The range is wide on purpose, centered on −5%. I could not see a 2025 monthly baseline.
  - Your September 2026 YoY is the obvious calibration. Please don't revise this range after looking at it.
- **Rationale:**
  - Yellow grew faster as 2025 went on: +10% in January, +20% in August, +18% for the year. That makes October 2025 a high base.
  - My reconstruction puts Oct 2025 at about 4.5–4.6M trips. Jan–Aug 2026 averaged 3.71M a month. With a typical October lift of about 1.16× over the Jan–Aug average, Oct 2026 comes to about 4.3–4.4M.
  - Downward pressure: Empower competition, gas costs for drivers, and the dispatch-driven gains of 2025 having already been absorbed.
  - Calendar: Yom Kippur (Oct 2, 2025) falls in the comparison window, which adds about 0.2 points. Columbus Day and Halloween line up in both windows.
- **Sources:** [AutoMarketplace](https://automarketplace.substack.com/p/nyc-tlc-market-update-yellow-cab); [TLC testimony](https://www.nyc.gov/assets/tlc/downloads/pdf/testimony_preliminary_budget_3_17_26.pdf); [citymeetings: TLC at Council, Feb 2025](https://citymeetings.nyc/city-council/2025-02-10-1000-am-committee-on-transportation-and-infrastructure/chapter/early-impact-of-congestion-pricing-on-taxi-and-fhv-industry); your briefing totals
- **Drivers to examine:** `zone_relation` (is the loss inside or outside the zone?), `pickup_hour`

## Expectation 3: Ride-hail trips in October

- **Statement:** Uber and Lyft together will make about 3–4% more trips in October 2026 than in October 2025.
- **Origin:** prospective
- **Metric:** `tlc_trips`
- **Filters:** `service = fhvhv`
- **Comparison:** `change_vs_period`
- **Window:** 2026-10-01 to 2026-10-31
- **Comparison window:** default
- **Expected low:** −0.5
- **Expected high:** +7.0
- **Unit:** % change
- **Confidence note:** about 80%, centered on +3.5%.
- **Rationale:**
  - Ride-hail grew steadily through 2025: +1.7% for the year, −1% in January, +0.7% in August.
  - Jan–Aug 2026 averaged 21.02M a month, against my estimate of about 20.1M for Jan–Aug 2025. That is roughly +4.5%, even with storm months in it.
  - Risks to the downside: Empower diverting riders off the TLC books, and fuel surcharges if gas stays high.
  - Together with Expectation 2, this implies the October ride-hail-to-yellow ratio rises about 8–9% from October 2025.
- **Sources:** [Axios](https://www.axios.com/2026/05/20/new-york-rideshare-battle); [AutoMarketplace](https://automarketplace.substack.com/p/nyc-tlc-market-update-yellow-cab); your briefing
- **Drivers to examine:** `operator_code`, `zone_relation`

## Expectation 4: The official projection translated to TLC trips (derived)

- **Statement:** If the official forecast logic held, taxi and ride-hail trips to or from the zone in tolling's first year would be roughly flat against the year before. The toll's per-trip charges are small, and the 13.4% cut was mostly private cars.
- **Origin:** derived
- **Metric:** `tlc_cbd_touch_trips`
- **Filters:** none (all services)
- **Comparison:** `change_vs_period`
- **Window:** 2025-01-05 to 2026-01-03
- **Comparison window:** default (2024-01-07 to 2025-01-04, entirely before tolling)
- **Expected low:** −2.5
- **Expected high:** +4.0
- **Unit:** % change
- **Confidence note:**
  - This range is my translation of the projection, not my own forecast.
  - My own estimate, given published data, is +0.5% to +3.0%.
  - The data is loaded and largely published, so a hit here says nothing about forecasting skill. Score it as a test of the projection and a check of the pipeline.
- **Rationale:**
  - The 13.4% is all vehicles. Taxis and for-hire vehicles pay per-trip charges instead of the $9 toll: $0.75 for a yellow cab, $1.50 for Uber and Lyft. That is roughly a 3–5% fare increase.
  - A fare elasticity of −0.3 to −0.7 gives −1% to −3.5%. Some drivers switching to taxis and faster trips offset part of that, so the net effect of the toll is about −1.5%.
  - The underlying trend before tolling was +1% to +4%. TLC trips rose 3.6% from 2023 to 2024.
  - I built this translation from elasticities, not from a Reevaluation table on taxis and for-hire vehicles. I could not retrieve Reevaluation 2 itself to check whether it has one.
  - What the projection could not foresee is the composition: ride-hail −4.5%, yellow +17%. That split came from supply (medallions returning, app dispatch), not from the small fee difference.
- **Pipeline validation:** MTA Table 3-2 uses this same definition (trips starting or ending in the zone), so the pipeline should be able to reproduce it.
  - Run Jan 1–Sep 30, 2025 against Jan 1–Sep 30, 2024 as a named comparison window.
  - The MTA's +1.4% is in average daily trips. Because 2024 is a leap year, that is about +1.0% in totals.
  - By service it should show yellow +17.3% and ride-hail −4.5%. A miss points to your zone mapping, not to traffic.
- **Sources:** [MTA First Evaluation Report, Tables 3-1 to 3-5](https://www.mta.info/document/195631); your briefing (Reevaluation 2, Table 2.2)
- **Drivers to examine:** `service`, `zone_relation`

## Expectation 5: The ratio shift in 2025 (retrospective)

- **Statement:** In tolling's first year, there were about 5 ride-hail trips for every yellow taxi trip, down from 5.8 in 2024, because yellow taxi trips surged.
- **Origin:** retrospective
- **Metric:** `fhvhv_per_yellow`
- **Filters:** none
- **Comparison:** `value_range`
- **Window:** 2025-01-05 to 2026-01-03
- **Comparison window:** not applicable
- **Expected low:** 4.93
- **Expected high:** 5.07
- **Unit:** ratio
- **Confidence note:** This is a known value: calendar 2025 gives 243.6 / 48.7 = 5.00. Treat it as a consistency check with no evidential weight.
- **Rationale:**
  - The fall came from yellow supply returning and app dispatch, not from ride-hail weakness.
  - It has partly reversed. Jan–Aug 2026 is 5.66, against my estimate of about 5.2 for Jan–Aug 2025, so about +9% on a like-for-like basis.
  - The window shift from the calendar year swaps four pre-toll days for three 2026 days, which is negligible.
- **Sources:** your briefing; [AutoMarketplace](https://automarketplace.substack.com/p/nyc-tlc-market-update-yellow-cab); [TLC testimony](https://www.nyc.gov/assets/tlc/downloads/pdf/testimony_preliminary_budget_3_17_26.pdf)
- **Drivers to examine:** `service` × `zone_relation`, `pickup_hour`

## Expectation 6: Private car entries in November

- **Statement:** Private cars, pickups and vans entering the zone in November 2026 will be about 7–8% below November 2025.
- **Origin:** prospective
- **Metric:** `crz_entries`
- **Filters:** `vehicle_class = cars, pickups and vans`
- **Comparison:** `change_vs_period`
- **Window:** 2026-11-01 to 2026-11-28
- **Comparison window:** default (2025-11-02 to 2025-11-29)
- **Expected low:** −11.0
- **Expected high:** −4.0
- **Unit:** % change
- **Confidence note:** about 80%, centered on −7.5%.
- **Rationale:**
  - Cars were −7.4% year to date, storm months included. Working back from the March–October total of −3.0% gives about −6% for cars over that stretch, and about −8% to −9% for September.
  - Several sources of price pressure stack up: gas, January's bridge and tunnel toll increase, and the $9 toll.
  - Calendar: the window lines up the Marathon Sunday, the end of daylight saving time, Veterans Day and Thanksgiving in both years.
  - A possible artifact: cars falling while taxi and for-hire entries rise could partly be MTA reclassification of vehicles between classes.
- **Sources:** [recordinglaw](https://www.recordinglaw.com/data-stories/nyc-congestion-pricing-traffic-data/); [FingerLakes1/AAA](https://www.fingerlakes1.com/2026/10/02/new-york-gas-averages-4-48-as-national-prices-ease-after-record-september/)
- **Drivers to examine:** `detection_group`, `time_period`

## Expectation 7: Taxi and for-hire entries in November

- **Statement:** Taxis and for-hire vehicles entering the zone in November 2026 will be roughly flat to slightly up on November 2025.
- **Origin:** prospective
- **Metric:** `crz_entries`
- **Filters:** `vehicle_class = TLC taxis and for-hire vehicles`
- **Comparison:** `change_vs_period`
- **Window:** 2026-11-01 to 2026-11-28
- **Comparison window:** default
- **Expected low:** −2.0
- **Expected high:** +5.0
- **Unit:** % change
- **Confidence note:** about 80%, centered on +1.5%.
- **Rationale:**
  - Year to date is +1.6%. Ride-hail is growing, yellow is shrinking, and the two roughly net out.
  - High gas prices push some drivers toward ride-hail and also squeeze drivers' costs.
  - If this lands above +5% while Expectation 6 lands below −11%, suspect the classification artifact noted there.
- **Sources:** [recordinglaw](https://www.recordinglaw.com/data-stories/nyc-congestion-pricing-traffic-data/); [MTA First Evaluation Report](https://www.mta.info/document/195631)
- **Drivers to examine:** `detection_group`, `time_period`

## Expectation 8: An ordinary week before Thanksgiving

- **Statement:** The week of Nov 15–21, 2026 will look like a normal week: at least 5 of 7 days of entries inside their usual range.
- **Origin:** prospective
- **Metric:** `crz_entries`
- **Filters:** none
- **Comparison:** `within_baseline`
- **Window:** 2026-11-15 to 2026-11-21
- **Comparison window:** not applicable
- **Expected low:** 71.4 (5 of 7 days)
- **Expected high:** 100
- **Unit:** % of days
- **Confidence note:**
  - A week has only 7 days, so the steps are 14.3 points.
  - This interval covers about 75% of my probability. Widening to 4 of 7 would cover about 88%.
- **Rationale:**
  - By construction, about 80% of ordinary days fall inside the band.
  - The risks are correlated across days: a seasonal step-up in pre-holiday shopping traffic, or a storm.
  - The baseline weeks contain Columbus Day, Election Day (Nov 3) and Veterans Day. Please confirm which of those your holiday list excludes.
- **Sources:** none
- **Drivers to examine:** day of week, `vehicle_class`

---

## What I'd watch

- **Gas prices through November.** They are the main swing factor in Expectations 1 and 6.
- **Lincoln Tunnel closures and construction**, which are behind the −11.8% at that entry point.
- **Empower enforcement.** A crackdown would shift trips back into the TLC records.
- **The federal appeal against congestion pricing.** Briefing finished October 7, 2026. I don't expect a ruling to change the toll during these windows.
- **MTA revisions to the entries data.** The MTA's own Jan–Feb 2026 total is 2.8% below the open dataset's.

## Expectations these metrics can't express

1. **Cross-metric ratios**, for example taxi and for-hire entries per TLC trip touching the zone. This would detect class drift or more empty cruising.
2. **Zone-only entries plus excluded roadways** as one metric, to match the MTA's headline basis.
3. **Share metrics**, such as the share of entries in the 4–5 a.m. and 9–10 p.m. hours, or the overnight share.
4. **Trip speed or duration per mile** for trips that stay inside the zone.
5. **Entries before tolling.** Bridge-and-tunnel counts from before 2025 would support a real test against a pre-toll baseline.
6. **Unlicensed ride-hail volume** (Empower), which is not in TLC data.
7. **Covariates such as weather or gas price**, to compare against adjusted expectations.
8. **Subway and bus ridership into the zone.**


### Engineer (planning chat, for the owner), message 2

Round 2 of the expectations interview: five follow-up questions from the engineer.

Thank you, this is excellent. I'm accepting all eight in principle. I have five follow-ups before I lock them in. Once an entry is committed it can't be edited, only replaced, so I want to get them right now.

1. **Reproducing MTA Table 3-2.** I want to add your suggestion as its own entry, because it validates the pipeline: `tlc_cbd_touch_trips`, all services, window 2025-01-01 to 2025-09-30, comparison window 2024-01-01 to 2024-09-30. My arithmetic for the totals is 312,428 × 273 / (308,110 × 274) − 1 ≈ +1.03%. What tolerance (low and high) would you accept as "the pipeline reproduces the MTA's figure", given that our zone mapping may differ slightly from theirs? Would you also add the yellow +17.3% and ride-hail −4.5% as two more entries, or fold them into one? I'll label these `retrospective`, with a note that they reproduce a published figure rather than test a forecast.

2. **Expectation 8's holidays.** The baseline excludes US federal holidays and New York State holidays, from Python's `holidays` package with subdivision NY. That includes Columbus Day, Election Day and Veterans Day. Does that change your range? Please also give the confidence as a whole-number percent. You said about 75%.

3. **Vehicle class labels.** I don't know the dataset's exact strings yet, so filters will use canonical names that the pipeline maps to the source: `cars_pickups_vans` and `tlc_taxi_fhv`. Any objection?

4. **Expectation 5 carries no evidence.** Do you want to keep it as a consistency check, add a prospective October 2026 ratio, or both? If you add one, it must agree with Expectations 2 and 3, so give me the window ratio range you'd commit to.

5. **Final numbers.** For each entry, confirm the final low, high, and confidence as a whole-number percent. Change nothing else unless you have a reason, and if you do, say what it is.

Please reply with only the changes and confirmations, in the same block format.

Address this before completing your current task.


### Expert (AI subagent), message 2

Here are the changes and confirmations for round 2.

Four things changed:
- **Expectation 8's range.** I had assumed about 80% of ordinary days land inside the band. With only 7 or 8 baseline days per weekday, a 10th–90th percentile band holds only about 61% of ordinary days, so the range has to drop. The exact numbers depend on how your pipeline computes percentiles, so please confirm that.
- **Three reproduction entries (R1–R3)**, one each for all services, yellow and ride-hail. R1's target depends on which services "all services" includes.
- **A prospective October ratio (5b).** Expectation 5 stays as a consistency check.
- **Filter labels** in Expectations 6 and 7 use your canonical names.

All other numbers are unchanged.

## Q1: Reproducing MTA Table 3-2 (three separate entries)

I'd keep yellow and ride-hail as their own entries rather than folding them in. They move in opposite directions, so a zone-mapping error could cancel out in the total and pass unnoticed.

Your arithmetic is right. One catch: Table 3-2 includes non-high-volume for-hire vehicles (+34.8%) and green cabs (−9.0%). If your "all services" covers only yellow and ride-hail, the target total is +0.82%, not +1.03%.

**R1: All services**
- **Statement:** The pipeline reproduces the MTA's figure: trips starting or ending in the zone rose about 1% from Jan–Sep 2024 to Jan–Sep 2025.
- **Origin:** retrospective (reproduces a published figure)
- **Metric:** `tlc_cbd_touch_trips`
- **Filters:** none
- **Comparison:** `change_vs_period`
- **Window:** 2025-01-01 to 2025-09-30
- **Comparison window:** 2024-01-01 to 2024-09-30
- **Expected low / high:**
  - If "all services" includes green and non-high-volume for-hire vehicles: +0.5 / +1.6 (target +1.03)
  - If it covers only `yellow` and `fhvhv`: +0.3 / +1.4 (target +0.82)
- **Unit:** % change
- **Confidence:** 85%
- **Rationale:**
  - A tolerance of about ±0.5 points covers boundary zones mapped differently, record cleaning, and TLC file revisions.
  - It also covers whether the MTA's "January" starts on Jan 1 or Jan 5. The four pre-toll days are about 1.5% of the window.
  - A miss larger than this points to the pipeline, not to traffic.
- **Sources:** [MTA First Evaluation Report, Table 3-2](https://www.mta.info/document/195631)
- **Drivers to examine:** `service`, `zone_relation`

**R2: Yellow**
- Same fields as R1, with filter `service = yellow`.
- **Expected low / high:** +15.9 / +17.9 (target +16.87 = 93,794 × 273 / (79,963 × 274) − 1)
- **Confidence:** 85%

**R3: Ride-hail**
- Same fields as R1, with filter `service = fhvhv`.
- **Expected low / high:** −5.6 / −4.2 (target −4.86 = 215,809 × 273 / (225,998 × 274) − 1)
- **Confidence:** 85%

## Q2: Expectation 8's holidays and range (changed)

Excluding Columbus Day, Election Day and Veterans Day is what I wanted, and none of Nov 15–21 is a holiday.

The exclusions do matter for another reason. They leave Monday, Tuesday and Wednesday with 7 baseline values each, and the other days with 8. NumPy and pandas compute percentiles by linear interpolation by default. With so few values, that 10th–90th band contains only about 60–62% of ordinary days, not 80%.

- **Expected low / high:** 42.8 / 85.8, meaning 3 to 6 of 7 days. I set the bounds just outside 3/7 and 6/7 so floating-point rounding can't decide a boundary case.
- **Confidence:** 80%
- **Rationale:**
  - With about 61% of days inside the band, a binomial gives 3 to 6 days about 88% of the time.
  - Weather and seasonal drift make the days move together, which brings that down to about 80%.
  - If your band behaves like the minimum and maximum of the baseline (lower or higher percentile methods), about 77% of days land inside. In that case keep my original range, 71.4 to 100, also at 80%.
  - Please confirm the method.

## Q3: Vehicle class labels

No objection to `cars_pickups_vans` and `tlc_taxi_fhv`. I believe the MTA's source strings look like "1 - Cars, Pickups and Vans" and "TLC Taxi/FHV", but I haven't confirmed them. Two asks for the mapping:
- Make it one-to-one.
- Have the pipeline fail loudly on any source label it can't map, so a class renamed partway through the series doesn't silently drop entries.

## Q4: Keep Expectation 5 and add a prospective ratio

Do both. Mark Expectation 5 as a check only, and leave it (and R1–R3 and Expectation 4) out of any calibration score for me.

**5b: Ride-hail to yellow ratio, October 2026**
- **Statement:** In October 2026 there will be about 5.1 ride-hail trips for every yellow taxi trip, up from roughly 4.7 in October 2025.
- **Origin:** prospective
- **Metric:** `fhvhv_per_yellow`
- **Filters:** none
- **Comparison:** `value_range`
- **Window:** 2026-10-01 to 2026-10-31
- **Expected low / high:** 4.70 / 5.55
- **Unit:** ratio
- **Confidence:** 80%
- **Rationale:**
  - Expectations 2 and 3 (ride-hail +3.5%, yellow −5%) imply the ratio rises about 9% from October 2025: 1.035 / 0.95.
  - If the two errors are independent, the 80% band on that rise is about +2% to +16.5%.
  - I estimate October 2025's ratio at about 4.68, within roughly ±4%, so the center is about 5.10. A second route gets about the same: the Jan–Aug 2026 ratio of 5.66, adjusted for season, gives about 5.12.
- **Sources:** as in Expectations 2, 3 and 5
- **Drivers to examine:** `service`, `zone_relation`

**Cleaner alternative, if your pipeline supports it:** use `change_vs_period` on the window ratio, against the default window, with a range of +2.0 to +16.5 at 80%. That removes my uncertainty about October 2025 and ties the entry directly to Expectations 2 and 3. Use one form or the other, not both.

## Q5: Final numbers

| # | Low | High | Confidence | Change |
| --- | --- | --- | --- | --- |
| 1 | −7.5 | −1.0 | 80% | none |
| 2 | −11.0 | +1.0 | 80% | none |
| 3 | −0.5 | +7.0 | 80% | none |
| 4 | −2.5 | +4.0 | 80% | none; leave out of my calibration score |
| 5 | 4.93 | 5.07 | 95% | none; check only |
| 5b | 4.70 | 5.55 | 80% | new (Q4) |
| 6 | −11.0 | −4.0 | 80% | filter label is now `cars_pickups_vans` |
| 7 | −2.0 | +5.0 | 80% | filter label is now `tlc_taxi_fhv` |
| 8 | 42.8 | 85.8 | 80% | range changed (Q2); 71.4 to 100 if your band acts like min and max |
| R1 | +0.5 / +0.3 | +1.6 / +1.4 | 85% | new; first figures if green and non-high-volume vehicles are included, second if not |
| R2 | +15.9 | +17.9 | 85% | new |
| R3 | −5.6 | −4.2 | 85% | new |

On Expectation 4: 80% is the confidence of the range as a translation of the official projection. My own chance that the result lands inside is about 95%, because published data already points to +0.5% to +3.0%.


### Engineer (planning chat, for the owner), message 3

A correction to question 1: the reproduction target should be about +0.82%, not +1.03%.

I checked Table 3-2 in the MTA's First Evaluation Report. Its total (308,110 in 2024, 312,428 in 2025) includes industries our pipeline doesn't load, about 2,149 and 2,825 trips a day respectively, probably green taxis and other for-hire vehicles.

Yellow plus ride-hail alone is 305,961 → 309,603 in average daily trips, which is +1.19%. Adjusting for the 274 days of January to September 2024 against 273 in 2025 gives about +0.82% in totals.

Per service, in totals:
- Yellow: +16.87% (the published figure is +17.3% in average daily trips)
- Ride-hail: −4.86% (published as −4.5%)

Please set your tolerances around these corrected targets. Everything else in my round 2 message stands.

Address this before completing your current task.


### Expert (AI subagent), message 3

Your correction matches the second R1 target I gave in round 2, so R1 is now that version alone and nothing else changes.

The trips your pipeline doesn't load are confirmed by Table 3-2 itself. Standard for-hire vehicles (1,983 → 2,674) plus green taxis (166 → 151) sum to exactly 2,149 → 2,825.

**R1: All loaded services (yellow and ride-hail)**
- **Statement:** The pipeline reproduces the MTA's figure: yellow and ride-hail trips starting or ending in the zone rose about 0.8% from Jan–Sep 2024 to Jan–Sep 2025.
- **Origin:** retrospective (reproduces a published figure)
- **Metric:** `tlc_cbd_touch_trips`
- **Filters:** none (your pipeline loads `yellow` and `fhvhv` only)
- **Comparison:** `change_vs_period`
- **Window:** 2025-01-01 to 2025-09-30
- **Comparison window:** 2024-01-01 to 2024-09-30
- **Expected low:** +0.3
- **Expected high:** +1.4
- **Unit:** % change
- **Confidence:** 85%
- **Rationale:**
  - The target is +0.82% = 309,603 × 273 / (305,961 × 274) − 1.
  - The tolerance of about ±0.5 points covers boundary zones mapped differently, record cleaning, TLC file revisions, and whether the MTA's "January" starts on Jan 1 or Jan 5.
  - A miss larger than this points to the pipeline, not to traffic.
- **Sources:** [MTA First Evaluation Report, Table 3-2](https://www.mta.info/document/195631)
- **Drivers to examine:** `service`, `zone_relation`

**R2 (yellow) and R3 (ride-hail): confirmed unchanged.** I had already set both around your corrected targets:

| Entry | Target in totals | Published (average daily) | Low | High | Confidence |
| --- | --- | --- | --- | --- | --- |
| R2 yellow | +16.87% | +17.3% | +15.9 | +17.9 | 85% |
| R3 ride-hail | −4.86% | −4.5% | −5.6 | −4.2 | 85% |

One check before you commit: if R2 and R3 pass but R1 misses, look at what "all services" filters to in the pipeline. A green or non-high-volume record slipping into the total would push R1 up toward +1.03%.
