import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tigerdiag.doctor import DoctorReport, doctor_report_to_dict


class DoctorTests(unittest.TestCase):
    def test_doctor_report_to_dict(self):
        report = DoctorReport(
            ports=[{"device": "/dev/cu.usbserial-1", "score": 10, "likely": True}],
            selected_port="/dev/cu.usbserial-1",
            selected_baud=38400,
            adapter={"identity": "ELM327 V1.4"},
            adapter_ok=True,
            ecu_ok=True,
            notes=["ready"],
        )

        data = doctor_report_to_dict(report)

        self.assertTrue(data["adapter_ok"])
        self.assertTrue(data["ecu_ok"])
        self.assertEqual(data["selected_baud"], 38400)
        self.assertEqual(data["adapter"]["identity"], "ELM327 V1.4")


if __name__ == "__main__":
    unittest.main()

