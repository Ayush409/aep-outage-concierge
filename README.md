# AEP Outage Concierge

Built for HackOHI/O 2026 (AEP challenge).

When a storm is coming, this app helps two groups of people:

- **Households** see how likely they are to lose power, how long it might take to come back, and what to do
  to get ready. They also get alerts before, during and after the outage.
- **AEP staff** see where outages are likely, which repairs are needed, how many crews it would take, and what
  the storm could cost.

It covers the Roanoke, Virginia area, using AEP's own map of its power lines and real damage reports from past
storms. You can also play out different storms (a snowstorm, a derecho, a tornado outbreak or an arctic freeze)
and watch them on a 3D map.

All numbers in the app are estimates from a model, not official AEP updates.

## What you can do in it

- See your home's outage risk (Low, Elevated, High or Severe) and a range for when power could return
- Follow a checklist to prepare, and save a copy to use offline
- Get alerts when a storm is coming, when power goes out, and when it comes back
- (AEP staff) View an outage map, a repair plan, storm costs, and a storm simulator with adjustable settings
- Ask questions in the built-in chat

## Tech stack

- **Website:** React, with MapLibre and deck.gl for the maps and 3D view
- **Server:** Python and FastAPI, with a SQLite database
- **Model and simulation:** NumPy, pandas, SciPy and scikit-learn
- **Written explanations:** AI turns the model's numbers into plain-language messages
- **Data:** AEP's map and damage data, plus weather from Open-Meteo

## How to download and run it

### 1. Install the tools

- [Python](https://www.python.org/downloads/) 3.11 or newer
- [Node.js](https://nodejs.org/) 20 or newer
- [Git](https://git-scm.com/downloads)

### 2. Download the project

```bash
git clone https://github.com/Ayush409/aep-outage-concierge.git
cd aep-outage-concierge
```

### 3. Set up Python

Mac or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The commands below assume this environment is active. If you open a new terminal, run the `activate`
line again first.

### 4. Unzip the data

Mac or Linux:

```bash
mkdir -p data/extracted/Data1 data/extracted/Data2 data/extracted/matched_upstream
unzip -n data/raw/Data1.zip -d data/extracted/Data1
unzip -n data/raw/Data2.zip -d data/extracted/Data2
unzip -n data/raw/matched_upstream.zip -d data/extracted/matched_upstream
```

Windows (PowerShell):

```powershell
Expand-Archive data\raw\Data1.zip -DestinationPath data\extracted\Data1
Expand-Archive data\raw\Data2.zip -DestinationPath data\extracted\Data2
Expand-Archive data\raw\matched_upstream.zip -DestinationPath data\extracted\matched_upstream
```

### 5. Build the data and the model

This takes about 10 minutes the first time, mostly downloading weather. Run these in order:

```bash
python scripts/export_damage.py
python scripts/prep_data.py
python scripts/fetch_weather.py
python scripts/train_model.py
python scripts/render_drawings.py
python scripts/seed_accounts.py
```

### 6. Start the app

Start the server:

```bash
python -m uvicorn app.main:app --app-dir backend --port 8000
```

Then open a **second** terminal in the project folder and start the website:

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Open **http://localhost:5173** in your browser.

### 7. Sign in

- Click **View the outage map anonymously** to look around without an account.
- Or sign in with a demo customer or AEP staff account. The logins and password are listed at the top of
  `scripts/seed_accounts.py`.

### Optional settings

Copy `backend/.env.example` to `backend/.env` to add optional settings, such as an AI key for written
messages or a Twilio account for real text messages. The app works without them; it uses standard message
templates and simulated texts instead.

## More detail

- [docs/technical-notes.md](docs/technical-notes.md): demo walkthrough, tests and how the code is organized
- [PLAN.md](PLAN.md): design, data findings and modelling decisions
- [data/README.md](data/README.md): what is in the challenge data
