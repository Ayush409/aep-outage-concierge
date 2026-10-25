"""Package saved training experiments for the operator evidence dashboard.

Run train_model.py with the four --output names below first. Never replaces the active model.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'processed'
EXPERIMENTS = [
    ('baseline', 'Current model (ridge 0.001)', 'model_baseline_review.json'),
    ('ridge100', 'Regularized (ridge 100)', 'model_ridge100_review.json'),
    ('ridge1000', 'Regularized (ridge 1000)', 'model_ridge1000_review.json'),
    ('nohistory', 'No spatial history (ridge 100)', 'model_nohistory_review.json'),
]


def build():
    active = (DATA / 'risk_model.json').read_bytes()
    active_model = json.loads(active)
    experiments = []
    for key, label, filename in EXPERIMENTS:
        model = json.loads((DATA / filename).read_text())
        if key == 'baseline':
            for field in ('coef', 'intercept', 'validation'):
                if field == 'validation':
                    for event, values in active_model[field].items():
                        for metric in ('predicted_damage', 'actual_damage', 'predicted_customers_out', 'actual_customers_out'):
                            assert model[field][event][metric] == values[metric], 'Active model no longer matches review'
                else:
                    assert model[field] == active_model[field], 'Active model no longer matches review'
        experiments.append(dict(id=key, label=label, settings=model['experiment'], validation=model['validation']))
    report = dict(active_model_sha256=hashlib.sha256(active).hexdigest(), experiments=experiments,
                  conclusion='Regularization reduces the largest overprediction, but all tested candidates still have worse Brier scores than the training-only constant baseline on both events. Ranking also weakens. No candidate has been promoted; reusing these hold-outs for model choices makes this exploratory evidence, not independent validation.',
                  next_steps=[
                      'Obtain verified outage start/end telemetry and unaffected-premise labels; downstream-of-damage labels are only a proxy.',
                      'Add independent storms across seasons and hazards, then reserve entire events for final evaluation.',
                      'Align damage occurrence times with weather; report dates may lag the physical failure.',
                      'Build historical features only from information available before the event for chronological validation.',
                      'Fit probability calibration only on separate training/calibration events and compare Brier scores, counts, ranking, and reliability on untouched storms.',
                      'Evaluate duration intervals separately against real restoration timestamps; a probability improvement does not validate repair times.',
                  ])
    output = ROOT / 'docs' / 'model_review.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Saved {output}; active model unchanged.')


if __name__ == '__main__':
    build()
