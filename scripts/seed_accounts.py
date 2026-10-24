"""Create the demo accounts (test values only - this app runs locally).

Customers are linked directly to anonymized premises chosen to show different situations, so the
demo does not depend on the address-lookup service. Their stored addresses are placeholder text
built from the anonymized road names in the challenge data (encrypted like real ones).

Demo logins (all share the password below):
  customer.rural@demo.aep.test       overhead line, rural, high exposure
  customer.suburban@demo.aep.test    underground service, suburban
  customer.medical@demo.aep.test     declared medical device (life-support flag in AEP data)
  operator@demo.aep.test             AEP operator
  supervisor@demo.aep.test           AEP operator

Run:  .venv/Scripts/python scripts/seed_accounts.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import db  # noqa: E402
from app.engines import simulate  # noqa: E402
from app.engines.data import grid  # noqa: E402
from app.security import encrypt, hash_password  # noqa: E402

DEMO_PASSWORD = "StormReady!2026"


def pick_premises():
    g = grid()
    res = simulate.run(simulate.Params(scenario="feb_2025"))
    p_out = res["p_out"]
    prem = g.prem.assign(p_out=p_out, out=res["median"]["out"])
    rural = prem[prem.overhead & prem.out & prem.city.isin(["BENT MOUNTAIN", "COPPER HILL", "ELLISTON", "BOONES MILL"])]
    suburban = prem[(prem.service_kind == "Underground") & (prem.city == "ROANOKE")]
    medical = prem[prem.life_support & prem.out]
    if medical.empty:
        medical = prem[prem.life_support]
    return (rural.sort_values("p_out").iloc[-1], suburban.sort_values("p_out").iloc[len(suburban) // 2],
            medical.sort_values("p_out").iloc[-1])


def main():
    db.init()
    rural, suburban, medical = pick_premises()
    people = [
        ("Riley Rural (demo)", "customer.rural@demo.aep.test", "customer", rural, "+15405550101", []),
        ("Sam Suburban (demo)", "customer.suburban@demo.aep.test", "customer", suburban, None, []),
        ("Morgan Medical (demo)", "customer.medical@demo.aep.test", "customer", medical, "+15405550103",
         ["medical_device"]),
        ("AEP Operator (demo)", "operator@demo.aep.test", "aep", None, None, []),
        ("AEP Supervisor (demo)", "supervisor@demo.aep.test", "aep", None, None, []),
    ]
    with db.tx() as con:
        for name, email, role, pr, phone, needs in people:
            con.execute("DELETE FROM users WHERE email = ?", (email,))
            cur = con.execute("INSERT INTO users(email, name, pw_hash, role, created) VALUES (?,?,?,?,?)",
                              (email, name, hash_password(DEMO_PASSWORD), role, time.time()))
            if role == "customer":
                address = f"{100 + int(pr.premise[-3:]) % 800} {pr.road.title()} Rd (demo), {pr.city.title()}, VA"
                con.execute("INSERT INTO customer_profiles(user_id, premise, address_enc, zip_enc, phone_enc, "
                            "needs_enc, alerts_sms, alerts_inapp) VALUES (?,?,?,?,?,?,1,1)",
                            (cur.lastrowid, pr.premise, encrypt(address), encrypt(pr.zip), encrypt(phone),
                             encrypt(json.dumps(needs))))
            print(f"  {role:8} {email}")
    print("seeded; password is in scripts/seed_accounts.py")


if __name__ == "__main__":
    main()
