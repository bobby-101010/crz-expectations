# 0012: Driver details the spec left open

Status: accepted (Phase 4, 2026-11-12). Approved by the owner in the Phase 4 plan.

## Context

Spec section 7.7 defines drivers as an additive breakdown: every slice is expected to move by the midpoint of the expected range, so the slice gaps sum to the total gap. Three details were open.

## Decision

- **`share_of_gap` is stored as the formula gives it,** the slice's gap over the total gap. It is null only when the total gap is exactly zero.
- **A slice with no value keeps its place** under the label `(none)`. Yellow taxis have no operator, and dropping the slice would break the sum.
- **One set of driver rows per scoring run.** The job reads the latest scoring run and reuses its `run_id`. Running it again for the same scoring run writes nothing.
- A slice present in only one of the two windows counts as zero in the other.
- Slices are ranked by the absolute size of their gap, with ties broken by label.

## What the first run showed (2026-11-12, scoring run `ea67059f`)

Four entries qualified: the derived entry and the three Table 3-2 reproductions. All four are held, so their total gaps are small, and that makes shares large and of both signs.

| Entry | Dimension | Largest gap | Second |
| --- | --- | --- | --- |
| `derived-cbd-touch-trips-first-year` | service | yellow +4,637,079 trips (+424%) | fhvhv -3,543,880 (-324%) |
| | zone_relation | pickup_in +665,512 (+61%) | dropoff_in +276,390 (+25%) |
| `retrospective-reproduce-mta-table-3-2-total` | service | fhvhv -3,533,646 (+7483%) | yellow +3,486,421 (-7383%) |
| `retrospective-reproduce-mta-table-3-2-fhvhv` | operator_code | HV0005 (Lyft) +2,058,044 (+7632%) | HV0003 (Uber) -2,031,079 (-7532%) |

Shares in each breakdown still sum to 100%. Gaps are in trips over the whole window.

## Consequences

- When an entry lands near the middle of its range, the gap in the metric's own unit is the readable number, and the share is not. The status page shows both.
- A breakdown can show two large opposite gaps that nearly cancel, as with yellow and ride-hail above. That is a finding about composition, located but not explained.
- For `tlc_cbd_touch_trips` the `zone_relation` breakdown has three slices, because the metric leaves out `neither`.
