import json
import tempfile
import unittest
from pathlib import Path

from vpnchecker.models import Batch, CheckerError, Location, Measurement, load_locations


def payload(download=12_562_500, upload=5_093_750, latency=10.25):
    return json.dumps(
        {
            "download": {"bandwidth": download},
            "upload": {"bandwidth": upload},
            "ping": {"latency": latency},
            "server": {"host": "test.invalid", "country": "Germany", "location": "Frankfurt"},
        }
    )


class InputTests(unittest.TestCase):
    def load(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locations.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return load_locations(path)

    def test_optional_city_and_explicit_region(self):
        self.assertEqual(self.load({"locations": [{"country": " Canada "}]}), [Location("Canada")])
        loc = self.load({"locations": [{"country": "USA", "region": "usa-new-york"}]})[0]
        self.assertEqual(loc.find_region(["usa-new-york"]), "usa-new-york")

    def test_bad_inputs(self):
        for value in [
            None,
            [],
            {},
            {"locations": []},
            {"locations": "bad"},
            {"locations": [None]},
            {"locations": [{}]},
            {"locations": [{"country": " "}]},
            {"locations": [{"country": 12}]},
            {"locations": [{"country": "US", "city": None}]},
        ]:
            with self.subTest(value=value), self.assertRaises(CheckerError):
                self.load(value)

    def test_invalid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            with self.assertRaises(CheckerError):
                load_locations(path)
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(CheckerError):
                load_locations(path)

    def test_exact_city_precedes_country(self):
        self.assertEqual(
            Location("Canada", "Toronto").find_region(["canada", "canada-toronto"]),
            "canada-toronto",
        )

    def test_case_spaces_fallback_and_missing(self):
        self.assertEqual(Location("USA", "New York").find_region(["usa-new-york"]), "usa-new-york")
        self.assertEqual(Location("CANADA", "Toronto").find_region(["canada"]), "canada")
        self.assertIsNone(Location("Canada").find_region(["canada-toronto"]))
        self.assertIsNone(Location("Canada", region="bad").find_region(["canada"]))


class MeasurementTests(unittest.TestCase):
    def test_units_and_fractional_precision(self):
        result = Measurement.from_json(payload())
        self.assertEqual(result.download_mbps, 100.5)
        self.assertEqual(result.upload_mbps, 40.75)
        self.assertEqual(result.latency_ms, 10.25)
        self.assertEqual(result.server_location, "Germany, Frankfurt")

    def test_reject_invalid_json_or_schema(self):
        for value in [
            "no json",
            "[]",
            "{}",
            "null",
            payload(download=-1),
            payload(upload=True),
            payload(latency=float("nan")),
            payload(download="100"),
            payload(latency=float("inf")),
        ]:
            with self.subTest(value=value), self.assertRaises(CheckerError):
                Measurement.from_json(value)

    def test_zero_bandwidth_is_valid(self):
        self.assertEqual(Measurement.from_json(payload(download=0)).download_mbps, 0)

    def test_all_metrics_are_averaged(self):
        batch = Batch(
            [
                Measurement(100.5, 20.25, 10, "a", "A"),
                Measurement(200.5, 40.75, 30, "b", "B"),
            ],
            ["one failed"],
        )
        summary = batch.summary()
        self.assertEqual(summary["DownloadMbps"], 150.5)
        self.assertEqual(summary["UploadMbps"], 30.5)
        self.assertEqual(summary["LatencyMs"], 20)
        self.assertEqual(summary["SuccessfulTests"], 2)
        self.assertEqual(summary["FailedTests"], 1)
        self.assertEqual(len(summary["Samples"]), 2)

    def test_empty_batch(self):
        with self.assertRaisesRegex(CheckerError, "All speed tests failed"):
            Batch([], ["failed"]).summary()
