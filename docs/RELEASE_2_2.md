# EdgeIQ v2.2 - Distribution and Portfolio Validation

## Scorecard Gates

The v2.2 scorecard is evidence-gated. The model reaches `validated` only after all
of these conditions pass:

- 100 settled paper entries verified by supported final-stat sources
- 500 independent, versioned settled props
- Populated accuracy segments for confidence, grade, sport, stat, and provider
- Passing chronological holdout validation
- Passing grouped walk-forward validation
- 50 reliable closing-line snapshots
- 100 calibrated props with mean absolute calibration error at or below 10 points
- 100 verified distribution forecasts whose middle-50% coverage is between 40%
  and 60%, and whose floor-to-ceiling coverage is between 70% and 90%

The distribution gate checks whether forecast ranges contain actual results at
approximately the frequency their labels imply. A narrow interval that misses
too often and an overly wide interval that contains nearly everything both fail.

## Fastest Responsible Path

1. Use **Results > Model > Auto Paper Samples** each slate day.
2. Keep the generated mix at two 2-leg cards and one each of 3, 4, and 5 legs.
3. Use only end-to-end verified props so official finals can settle every leg.
4. Avoid repeating exact player/stat/line combinations in the same batch.
5. Run **Recheck Final Stats** after games finish.
6. Refresh the scorecard and follow the displayed **How to reach v2.2** actions.

Paid results still inform performance reporting, but paper entries are the safer
way to accumulate broad validation evidence. More samples do not guarantee that
a gate passes; calibration, interval coverage, and chronological tests must also
remain within their stated limits.
