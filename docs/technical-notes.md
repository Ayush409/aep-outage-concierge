# Technical notes

These notes were the project README before it was simplified. For setup, see the main [README](../README.md).
The design, data findings and modelling decisions are in [PLAN.md](../PLAN.md).

## Customer demonstration

With `DEV_MODE=1`, the login page offers anonymous overhead, underground, and medical-needs demo households.
Each creates a separate synthetic customer account. In My Status, start the storm journey and advance through
preparation, outage, a revised estimate, and restoration. The repair-access slider reruns the model;
the comparison and map use the same assumptions. Results may change only slightly or remain unchanged.
Practice alerts respect in-app preferences, preserve history, and never send SMS.

The preparation checklist saves progress per household and scenario. The Ready Plan download is a self-contained
HTML file for offline use, with its calculation time and a stale-information notice. Address and declared needs
are excluded unless explicitly selected. Downloaded copies remain on the device after account deletion.

Set `AI_ENABLED=0` in the backend environment to disable Claude calls and use template responses.
This does not disable account/checklist storage. The underlying risk model remains experimental:
its bands are planning indicators, not validated outage probabilities. No live utility-confirmation feed is connected.

For a single-server build: `npm --prefix frontend run build`, then the API also serves the app on port 8000.

## Checks

`python -m unittest discover -s tests` and
`node --test frontend/src/components/timeline.test.js frontend/src/components/offlinePlan.test.js`.

## Project layout

| Path | What |
|---|---|
| `scripts/` | Data prep, weather download, model training, demo accounts |
| `backend/app/engines/` | Risk model, structure-drawing repair kits, crew scheduling + Monte Carlo restoration, costs, scenarios |
| `backend/app/main.py` | API: auth, customer and AEP (role-checked) routes, alerts |
| `backend/app/ai.py` | Claude-written explanations/messages from engine facts only; template fallback |
| `frontend/src/pages/` | Customer tabs, AEP tabs, 3D simulation |

## Source data

- [`data/`](../data/README.md): original GIS and upstream-topology archives, labor-hour workbook.
- [`HackOHIO_2026_AI_Outage_Concierge_Challenge.docx`](HackOHIO_2026_AI_Outage_Concierge_Challenge.docx): challenge requirements.
- [`structure_drawings.pdf`](structure_drawings.pdf): sample distribution structure diagrams.
