"""Regression checks for a shared customer/map outcome and complete playback."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.engines import views


def run(starts, ends):
    ends = np.array(ends, dtype=float)
    return dict(out=ends > 0, st=np.array(starts), rest=ends,
                dev_time=ends, dev_start=np.array(starts), when=np.array([1.8, 2.2]),
                idx=np.array([0, 1]), finish=ends, iso=np.array([0, 1]))


class RestorationViewsTests(unittest.TestCase):
    def setUp(self):
        self.grid = SimpleNamespace(
            prem=pd.DataFrame(dict(service_kind=["Overhead"] * 2, life_support=[False] * 2,
                                   city=["roanoke"] * 2, zip=["24012"] * 2, customers=[6, 8])),
            dev=pd.DataFrame(dict(kind=["fuse"] * 2, customers=[6, 8])),
            cells=pd.DataFrame(dict(lon=[-80., -79.9], lat=[37.2, 37.3])),
            assets=pd.DataFrame(dict(lon=[-80., -79.9], lat=[37.2, 37.3], asset_type=["fuse"] * 2)),
            prem_cell=np.array([0, 1]), prem_customers=np.array([6, 8]),
            chain_of=lambda i: pd.DataFrame(index=[i]),
        )
        self.med = run([2.2, 1.8], [10.2, 100.4])
        self.res = dict(
            median=self.med, runs=[run([1., 1.], [6., 8.]), self.med],
            weather_hours=240, time=["2011-04-27T00:00:00"], scenario=dict(kind="scenario"),
            p_out=np.array([.5, .5]), contrib=np.zeros((2, 1)), dev_rate=np.zeros(2),
            peak=pd.DataFrame(dict(gust_max=[30.] * 2, frz=[0.] * 2, snow=[0.] * 2,
                                   tmin=[40.] * 2, tmax=[60.] * 2)), confidence=dict(level="Low"),
        )
        for target, value in [("grid", self.grid), ("risk.model", SimpleNamespace(meta={"labels": ["Wind"]})),
                              ("risk.band_outcome", {})]:
            mock = patch.object(views, target, return_value=value) if "." not in target else patch(
                f"app.engines.views.{target}", return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_customer_dates_match_map_run_and_keep_uncertainty(self):
        frames = views.frames(self.res)
        home = views.premise_status(self.res, 0)
        timeline = home["event"]["timeline"]
        self.assertEqual(timeline["power_lost"], 2)
        self.assertEqual(timeline["restored"], 11)
        self.assertEqual(home["event"]["all_restored_hour"], frames["all_restored_hour"])
        self.assertEqual(frames["all_restored_hour"], 101)
        self.assertGreater(home["restoration"]["p90"], home["restoration"]["p10"])
        self.assertEqual(frames["out"][0][10], 6)
        self.assertEqual(frames["out"][0][11], 0)

    def test_short_scenario_has_no_weather_padding_and_long_repairs_are_not_clipped(self):
        frames = views.frames(self.res)
        self.assertEqual(frames["hours"][-1], 102)
        self.assertEqual(frames["total"][-1], 0)
        self.res["weather_hours"] = 8
        self.assertEqual(views.frames(self.res)["hours"][-1], 102)

    def test_live_retains_full_forecast(self):
        self.res["scenario"]["kind"] = "live"
        self.assertEqual(views.frames(self.res)["hours"][-1], 239)

    def test_home_can_stay_on_in_map_while_other_runs_predict_an_outage(self):
        self.med["out"][0] = False
        self.med["rest"][0] = 0
        home = views.premise_status(self.res, 0)
        self.assertIsNone(home["event"]["timeline"])
        self.assertIsNotNone(home["restoration"])
        self.assertEqual(home["event"]["all_restored_hour"], 101)

    def test_no_damage(self):
        self.res.update(median=None, runs=[])
        self.assertEqual(views.frames(self.res)["hours"], [])
        home = views.premise_status(self.res, 0)
        self.assertIsNone(home["event"]["timeline"])
        self.assertIsNone(home["event"]["all_restored_hour"])


if __name__ == "__main__":
    unittest.main()
