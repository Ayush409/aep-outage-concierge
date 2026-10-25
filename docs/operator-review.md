# Operator experience and prediction review

## What changed

Restoration Planner now shows a restoration trajectory, both restoration milestones with P10/P90 ranges,
access and equipment flags, crew assumptions, and an initially selected repair kit. Job counts are explicitly
limited to the returned schedule (up to 400 jobs). Downstream exposure is not summed or presented as guaranteed
restoration benefit. Simulation and Business Impact remain the places to test operational assumptions and costs.

Model & Audit separates validation, data/assumptions, and searchable activity. Percentage charts use a fixed
0–100% axis, disclose customer counts, and label topology-derived outcomes as proxies. Large premise counts
are not independent storm samples. Operator text is larger while detailed evidence remains available.

## What the data supports

The repository contains 1,448 training damage records: 1,070 ice, 184 wind, and 194 tropical-storm reports.
There are two storm periods, 44,622 cell/day training rows, and 244,662 customer-weight units in validation.
57 January reports are excluded by the existing training specification. Labels are constructed by tracing
recorded damaged devices downstream, not by comparing against verified meter/OMS outage histories.

The baseline was reproduced without replacing `risk_model.json`. Helene damage predictions are 6,043.6 versus
194 recorded; the wind-phase predictions are 58.1 versus 184. Brier scores are 0.62007 and 0.11685 respectively,
versus training-only constant baselines of 0.08248 and 0.10763 (lower is better).

Ridge 100 reduces those damage predictions to 933.4 and 126.9; Brier scores improve to 0.19172 and 0.11231,
but still lose to the constant baseline. Ridge 1000 and ridge 100 without spatial history were also tested.
All experiments, including weaker alternatives, are retained in `model_review.json`. No candidate was promoted.

These comparisons reuse the two hold-outs and are exploratory. Do not claim independent accuracy improvement.
Regularization reduces extreme extrapolation in these experiments; it does not establish the causal source of
all error. Additional concerns include report-date/weather alignment, scarce hazard diversity, correlated
network labels, and spatial-history features that are leave-event-out but not strictly chronological.
The existing pooled monotonic band outcomes collapse to the same value across all bands; they are not useful
as distinct calibrated probabilities and are no longer displayed as such in the operator legend.

## Reproduce

Use the project's Python environment with requirements installed:

```powershell
python scripts/train_model.py --output data/processed/model_baseline_review.json
python scripts/train_model.py --ridge 100 --output data/processed/model_ridge100_review.json
python scripts/train_model.py --ridge 1000 --output data/processed/model_ridge1000_review.json
python scripts/train_model.py --ridge 100 --no-history --output data/processed/model_nohistory_review.json
python scripts/build_model_review.py
```

The API exposes this experiment report only when its model fingerprint matches the active model file.
Do not tune probabilities on the displayed test outcomes and then report those same events as unseen validation.
Next: obtain timestamped outage/non-outage labels, collect additional independent storms, calibrate on separate
events, and reserve untouched storms for probability, count, ranking, and duration validation.

## Challenge and rubric alignment

The AEP brief pages 3 and 5 and keynote pages 31–32 emphasize credible ranges, visible assumptions, changed-input
effects, and human-readable uncertainty. The rubric also rewards investigation and learning from failure.
The repair plan connects topology, labor, weather constraints, and customer impact; the experiment comparison
shows an actual investigated limitation and a justified decision. User research and independent validation
remain outstanding evidence, not accomplishments implied by the interface.
