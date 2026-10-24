# AEP HackOHI/O 2026 - AI Outage Concierge

A storm is coming to Roanoke, VA. Customers see their outage risk, how long restoration could take, what to do,
and get alerts. AEP operators see risk, damage, % out by ZIP/circuit, the crew job plan, and business impact.
Anyone can replay real local storms or drop famous storms onto Virginia and watch it play out in 3D.

The design, data findings and modelling decisions are in [PLAN.md](PLAN.md).

## Run it

Requirements: Python 3.11+ and Node 20+.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Unzip the challenge data first (see [data/README.md](data/README.md) - into `data/extracted/`), then build the data and model (about 10 minutes, mostly the weather download):

```bash
.venv/Scripts/python scripts/export_damage.py
.venv/Scripts/python scripts/prep_data.py
.venv/Scripts/python scripts/fetch_weather.py
.venv/Scripts/python scripts/train_model.py
.venv/Scripts/python scripts/render_drawings.py
.venv/Scripts/python scripts/seed_accounts.py
```

Start the API and the web app (two terminals):

```bash
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
```

```bash
npm --prefix frontend install && npm --prefix frontend run dev
```

Open http://localhost:5173. Demo logins (customers and AEP operators) are listed at the top of
`scripts/seed_accounts.py`. Optional settings (Claude API key, Twilio) go in `backend/.env` - see
`backend/.env.example`.

For a single-server build: `npm --prefix frontend run build`, then the API also serves the app on port 8000.

## Layout

| Path | What |
|---|---|
| `scripts/` | Data prep, weather download, model training, demo accounts |
| `backend/app/engines/` | Risk model, structure-drawing repair kits, crew scheduling + Monte Carlo restoration, costs, scenarios |
| `backend/app/main.py` | API: auth, customer and AEP (role-checked) routes, alerts |
| `backend/app/ai.py` | Claude-written explanations/messages from engine facts only; template fallback |
| `frontend/src/pages/` | Customer tabs, AEP tabs, 3D simulation |

## Source data

- [`data/`](data/README.md): original GIS and upstream-topology archives, labor-hour workbook.
- [`docs/HackOHIO_2026_AI_Outage_Concierge_Challenge.docx`](docs/HackOHIO_2026_AI_Outage_Concierge_Challenge.docx): challenge requirements.
- [`docs/structure_drawings.pdf`](docs/structure_drawings.pdf): sample distribution structure diagrams.
