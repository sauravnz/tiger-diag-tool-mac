import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tigerdiag.bundle import (
    format_doctor_only_html,
    format_doctor_only_summary,
    next_report_directory,
    parse_status_mask,
    write_discovery_artifacts,
)
from tigerdiag.elm327 import ElmError


class BundleTests(unittest.TestCase):
    def test_parse_status_mask(self):
        self.assertEqual(parse_status_mask("FF"), 0xFF)
        self.assertEqual(parse_status_mask("08"), 0x08)

    def test_parse_status_mask_rejects_out_of_range(self):
        with self.assertRaises(ElmError):
            parse_status_mask("100")

    def test_next_report_directory_adds_suffix_when_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 6, 1, 12, 30, 5)
            first = next_report_directory(root, now=now)
            first.mkdir()
            second = next_report_directory(root, now=now)
            self.assertEqual(second.name, "tigerdiag-20260601-123005-2")

    def test_format_doctor_only_summary(self):
        text = format_doctor_only_summary(
            {
                "adapter_ok": False,
                "ecu_ok": False,
                "ecu_error": "no data",
                "notes": ["Check ignition."],
            }
        )
        self.assertIn("did not reach the ECU", text)
        self.assertIn("Check ignition.", text)

    def test_format_doctor_only_html(self):
        html = format_doctor_only_html(
            {
                "adapter_ok": False,
                "ecu_ok": False,
                "ecu_error": "<no data>",
                "notes": ["Check ignition."],
            }
        )
        self.assertIn("<!doctype html>", html)
        self.assertIn("&lt;no data&gt;", html)
        self.assertIn("Check ignition.", html)

    def test_write_discovery_artifacts_generates_profile_when_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            discovery_path, profile_path = write_discovery_artifacts(
                Path(tmp),
                {
                    "modules": [
                        {
                            "tx_header": "720",
                            "response_kind": "positive",
                            "dtc_count": 0,
                            "raw_lines": ["728 03 59 02 FF"],
                        }
                    ]
                },
                protocol="can_11_500",
            )

            self.assertTrue(discovery_path.exists())
            self.assertIsNotNone(profile_path)
            self.assertTrue(profile_path.exists())

    def test_write_discovery_artifacts_skips_profile_when_no_usable_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            discovery_path, profile_path = write_discovery_artifacts(
                Path(tmp),
                {"modules": [{"tx_header": "7E0", "response_kind": "other", "raw_lines": []}]},
                protocol="can_11_500",
            )

            self.assertTrue(discovery_path.exists())
            self.assertIsNone(profile_path)


if __name__ == "__main__":
    unittest.main()
