# Recommendation Model Track Record

The recommendation proof drawer loads the existing model-track-record endpoint only when opened. It filters by model version, sport, stat, provider, and direction. The response is cached in the browser for five minutes to avoid a database query for every visible recommendation.

The record uses the first locked pregame forecast for each independent market within the same model/provider/direction. Only identity-linked, nonlegacy, versioned predictions with official settled Win/Loss evidence are counted in hit rate, mean predicted probability, calibration gap, and Brier score. Pushes and unresolved predictions are reported separately. Records from different providers or model versions are not pooled into an "independent games" count.

Fewer than 100 resolved decisions display a small-sample warning. An empty segment displays unavailable. If the query reaches its 5,000-record window, the compact view withholds performance rates and directs the user to Results for narrower inspection. These descriptive metrics do not prove profitability or override paid-entry release gates.
