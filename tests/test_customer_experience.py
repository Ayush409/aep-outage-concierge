import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.update(JWT_SECRET="isolated-test-secret", FIELD_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                  AI_ENABLED="0", TWILIO_ACCOUNT_SID="", TWILIO_AUTH_TOKEN="", TWILIO_FROM_NUMBER="")
from app import db, experience, main
from app.security import encrypt, require_customer, require_aep


def status_for(result, _):
    access = result["access"]
    return dict(risk=dict(band="High"), restoration=dict(p10=4 * access, p50=8 * access, p90=12 * access),
                event=dict(timeline=dict(power_lost=5, restored=5 + 8 * access), all_restored_hour=30 * access))


class CustomerExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        path.start(); self.addCleanup(path.stop)
        db.init()
        with db.tx() as con:
            for uid in (1, 2):
                con.execute("INSERT INTO users(id,email,name,pw_hash,role,created) VALUES (?,?,?,'unused','customer',0)",
                            (uid, f"{uid}@test.invalid", "Test household"))
                con.execute("INSERT INTO customer_profiles(user_id,premise,address_enc,zip_enc,needs_enc) VALUES (?,?,?,?,?)",
                            (uid, "test", encrypt("Test"), encrypt("24012"), encrypt("[]")))
        self.user = dict(id=1, role="customer", name="Test", email="1@test.invalid")
        main.app.dependency_overrides[require_customer] = lambda: self.user
        main.app.dependency_overrides[require_aep] = lambda: dict(id=99, role="aep")
        self.addCleanup(main.app.dependency_overrides.clear)
        for mock in (patch.object(main, "sim", side_effect=lambda p: dict(access=p.access_mult)),
                     patch.object(main, "_premise_idx", return_value=0),
                     patch.object(main.views, "premise_status", side_effect=status_for)):
            mock.start(); self.addCleanup(mock.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def step(self, action, access=1):
        return self.client.post("/api/me/journey", json=dict(scenario="snow_storm", action=action, access_mult=access))

    def notifications(self):
        with db.tx() as con:
            return [dict(r) for r in con.execute("SELECT * FROM notifications WHERE user_id=1 ORDER BY id")]

    def test_full_journey_is_ordered_private_and_preserves_history(self):
        self.assertEqual(self.step("restore").status_code, 409)
        for action, access in [("start", 1), ("outage", 1), ("update", 2), ("restore", 2)]:
            response = self.step(action, access)
            self.assertEqual(response.status_code, 200, response.text)
        messages = self.notifications()
        self.assertEqual([m["kind"] for m in messages], experience.STAGES)
        self.assertTrue(all(m["channel"] == "in-app" and "[Practice simulation]" in m["body"] for m in messages))
        self.assertEqual(response.json()["change"]["typical_hours_delta"], 8)
        self.assertEqual(self.step("restore").status_code, 409)
        self.step("restart")
        self.assertEqual(len(self.notifications()), 5)

    def test_unchanged_estimate_does_not_generate_false_update(self):
        self.step("start"); self.step("outage")
        result = self.step("update", 1).json()
        self.assertFalse(result["change"]["changed"])
        self.assertEqual(len(self.notifications()), 2)

    def test_opt_out_and_live_mode_are_respected(self):
        with db.tx() as con:
            con.execute("UPDATE customer_profiles SET alerts_inapp=0 WHERE user_id=1")
        self.step("start"); self.step("outage")
        self.assertEqual(self.notifications(), [])
        response = self.client.post("/api/me/journey", json=dict(scenario="live", action="start"))
        self.assertEqual(response.status_code, 422)

    def test_checklist_is_scoped_to_signed_in_customer(self):
        body = dict(scenario="snow_storm", task_key="a" * 24, done=True)
        self.assertEqual(self.client.put("/api/me/checklist", json=body).status_code, 200)
        with db.tx() as con:
            self.assertEqual(con.execute("SELECT user_id FROM preparation_checks").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM preparation_checks WHERE user_id=2").fetchone()[0], 0)

    def test_operator_dispatch_is_single_stage_deduplicated_and_live_confirmation_blocked(self):
        with patch.object(main, "_send_sms") as sms:
            for _ in range(2):
                response = self.client.post("/api/aep/alerts/send?scenario=snow_storm&kind=pre_storm")
                self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(self.notifications()), 1)
            self.assertEqual(response.json()["messages"], 0)
            self.client.post("/api/aep/alerts/send?scenario=snow_storm&kind=outage_confirmed")
            self.client.post("/api/aep/alerts/send?scenario=snow_storm&kind=estimate_updated")
            self.assertEqual(len(self.notifications()), 2)
            self.assertEqual(self.client.post("/api/aep/alerts/send?scenario=live&kind=restored").status_code, 409)
            sms.assert_not_called()

    def test_anonymous_household_sees_map_only(self):
        main.app.dependency_overrides.clear()  # use the real role checks
        guest = TestClient(main.app)  # fresh browser: no customer session
        self.assertIn(guest.post("/api/auth/demo", json=dict(household="medical")).status_code, (404, 405))  # removed
        self.assertEqual(guest.post("/api/auth/guest").status_code, 200)
        self.assertEqual(guest.get("/api/auth/me").json()["role"], "guest")
        for path in ("/api/me/status", "/api/me/profile", "/api/aep/settings"):
            self.assertEqual(guest.get(path).status_code, 403, path)

    def test_model_review_is_hidden_when_model_fingerprint_changes(self):
        import hashlib
        root = Path(self.temp.name)
        (root / 'docs').mkdir()
        model_file = root / 'model.json'
        model_file.write_bytes(b'original model')
        report = dict(active_model_sha256=hashlib.sha256(model_file.read_bytes()).hexdigest(), experiments=[])
        (root / 'docs' / 'model_review.json').write_text(json.dumps(report))
        active_model = main.risk.model()
        with patch.object(main, 'ROOT', root), patch.object(main.risk, 'MODEL_PATH', model_file), patch.object(main.risk, 'model', return_value=active_model):
            response = self.client.get('/api/aep/model')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['review'], report)
            model_file.write_bytes(b'retrained model')
            self.assertIsNone(self.client.get('/api/aep/model').json()['review'])

    def test_task_ids_are_stable_and_needs_are_prioritized(self):
        tips = dict(your_needs=["Arrange backup"], now=["Charge phone", "Arrange backup"], if_out=["Keep informed"])
        tasks = experience.checklist(tips)
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0]["group"], "your_needs")
        self.assertTrue(experience.checklist(tips, [tasks[0]["key"]])[0]["done"])


if __name__ == "__main__":
    unittest.main()
