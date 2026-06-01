import tempfile
import unittest
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tigerdiag.report import analyze_files, compare_reports, format_analysis, format_analysis_html, format_comparison


class ReportTests(unittest.TestCase):
    def test_analyze_standard_and_module_reports(self):
        standard = {
            "vin": "SMTTREXAMPLE12345",
            "mil": {"on": True, "reported_dtc_count": 1},
            "dtcs": {
                "stored": [
                    {
                        "code": "P0171",
                        "description": "System too lean, bank 1",
                        "suggestion": "Inspect intake leaks.",
                    }
                ],
                "pending": [],
                "permanent": [],
            },
            "snapshot": [
                {
                    "pid": "42",
                    "name": "control module voltage",
                    "value": 11.8,
                    "unit": "V",
                    "raw": ["0x2E", "0x18"],
                }
            ],
            "freeze_frame": {
                "frame": 0,
                "dtc": "P0171",
                "readings": [
                    {
                        "pid": "05",
                        "name": "coolant temperature",
                        "value": 82,
                        "unit": "deg C",
                        "raw": ["0x7A"],
                    }
                ],
            },
        }
        modules = {
            "profile": "test",
            "modules": [
                {
                    "module": {"name": "ABS candidate", "tx_header": "760"},
                    "responded": True,
                    "error": None,
                    "raw_lines": ["768 07 59 02 FF 41 00 00 88"],
                    "dtcs": [
                        {
                            "raw": "410000",
                            "code": "C0100-00",
                            "status": "0x88",
                            "status_flags": ["confirmed", "warning_indicator_requested"],
                            "description": "Chassis diagnostic trouble code",
                            "suggestion": "Inspect ABS wiring.",
                        }
                    ],
                },
                {
                    "module": {"name": "Instruments candidate", "tx_header": "720"},
                    "responded": False,
                    "error": "no data",
                    "raw_lines": [],
                    "dtcs": [],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            standard_path = Path(tmp) / "standard.json"
            modules_path = Path(tmp) / "modules.json"
            standard_path.write_text(json.dumps(standard), encoding="utf-8")
            modules_path.write_text(json.dumps(modules), encoding="utf-8")

            report = analyze_files(str(standard_path), str(modules_path))

        self.assertEqual(report.vin, "SMTTREXAMPLE12345")
        self.assertEqual([finding.code for finding in report.findings], ["C0100-00", "VOLTAGE_LOW", "P0171"])
        self.assertEqual(report.findings[0].severity, "high")
        self.assertEqual(report.module_responses["ABS candidate"], "responded with 1 DTC(s)")
        self.assertEqual(report.module_responses["Instruments candidate"], "no response (no data)")
        html = format_analysis_html(report)
        self.assertIn("<!doctype html>", html)
        self.assertIn("C0100-00", html)
        self.assertIn("ABS candidate", html)

    def test_format_no_findings(self):
        report = analyze_files_dict_for_test(
            {
                "vin": None,
                "mil": {"on": False, "reported_dtc_count": 0},
                "dtcs": {"stored": [], "pending": [], "permanent": []},
                "snapshot": [],
                "freeze_frame": None,
            }
        )
        text = format_analysis(report)
        self.assertIn("No DTCs were found", text)

    def test_freeze_frame_finding_when_code_not_in_standard_dtcs(self):
        report = analyze_files_dict_for_test(
            {
                "vin": None,
                "mil": {"on": False, "reported_dtc_count": 0},
                "dtcs": {"stored": [], "pending": [], "permanent": []},
                "snapshot": [],
                "freeze_frame": {"frame": 0, "dtc": "P0300", "readings": []},
            }
        )
        self.assertEqual([finding.code for finding in report.findings], ["P0300"])

    def test_compare_reports(self):
        before = {
            "vin": None,
            "mil": {"on": True, "reported_dtc_count": 2},
            "dtcs": {
                "stored": [
                    {"code": "P0171", "description": "System too lean", "suggestion": "Check intake leaks."},
                    {"code": "P0300", "description": "Misfire", "suggestion": "Check ignition."},
                ],
                "pending": [],
                "permanent": [],
            },
            "snapshot": [],
            "freeze_frame": None,
        }
        after = {
            "vin": None,
            "mil": {"on": True, "reported_dtc_count": 2},
            "dtcs": {
                "stored": [
                    {"code": "P0300", "description": "Misfire", "suggestion": "Check ignition."},
                    {"code": "P0562", "description": "System voltage low", "suggestion": "Check battery."},
                ],
                "pending": [],
                "permanent": [],
            },
            "snapshot": [],
            "freeze_frame": None,
        }

        with tempfile.TemporaryDirectory() as tmp:
            before_path = Path(tmp) / "before.json"
            after_path = Path(tmp) / "after.json"
            before_path.write_text(json.dumps(before), encoding="utf-8")
            after_path.write_text(json.dumps(after), encoding="utf-8")

            report = compare_reports(str(before_path), None, str(after_path), None)

        self.assertEqual([finding.code for finding in report.resolved], ["P0171"])
        self.assertEqual([finding.code for finding in report.persistent], ["P0300"])
        self.assertEqual([finding.code for finding in report.new], ["P0562"])
        text = format_comparison(report)
        self.assertIn("Resolved: 1", text)
        self.assertIn("Persistent: 1", text)
        self.assertIn("New: 1", text)


def analyze_files_dict_for_test(standard):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "standard.json"
        path.write_text(json.dumps(standard), encoding="utf-8")
        return analyze_files(str(path), None)


if __name__ == "__main__":
    unittest.main()
