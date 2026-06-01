import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tigerdiag.pids import (
    FreezeFrameReport,
    PidReading,
    decode_supported_pid_block,
    freeze_frame_to_dict,
    fuel_trim,
    read_freeze_frame_dtc,
    read_freeze_pid_payload,
    rpm,
    snapshot_to_dict,
    voltage,
)


class PidTests(unittest.TestCase):
    def test_decode_supported_pid_block(self):
        supported = decode_supported_pid_block(0x00, [0x98, 0x18, 0x00, 0x01])
        self.assertIn("01", supported)
        self.assertIn("04", supported)
        self.assertIn("05", supported)
        self.assertIn("0C", supported)
        self.assertIn("20", supported)

    def test_rpm_decoder(self):
        self.assertEqual(rpm([0x1A, 0xF8]), 1726.0)

    def test_voltage_decoder(self):
        self.assertEqual(voltage([0x2E, 0xE0]), 12.0)

    def test_fuel_trim_decoder(self):
        self.assertEqual(fuel_trim([0x80]), 0.0)

    def test_snapshot_to_dict(self):
        data = snapshot_to_dict([PidReading("42", "control module voltage", 12.5, "V", [0x30, 0xD4])])
        self.assertEqual(data[0]["pid"], "42")
        self.assertEqual(data[0]["raw"], ["0x30", "0xD4"])

    def test_freeze_frame_to_dict(self):
        data = freeze_frame_to_dict(
            FreezeFrameReport(
                frame=0,
                dtc="P0171",
                readings=[PidReading("05", "coolant temperature", 82, "deg C", [0x7A])],
            )
        )
        self.assertEqual(data["dtc"], "P0171")
        self.assertEqual(data["readings"][0]["value"], 82)

    def test_read_freeze_pid_payload_strips_frame_number(self):
        elm = FakeElm({"020500": ["42 05 00 7A"]})
        self.assertEqual(read_freeze_pid_payload(elm, "05", frame=0), [0x7A])

    def test_read_freeze_frame_dtc(self):
        elm = FakeElm({"020200": ["42 02 00 01 71"]})
        self.assertEqual(read_freeze_frame_dtc(elm), "P0171")


class FakeElm:
    def __init__(self, responses):
        self.responses = responses

    def command(self, command):
        return self.responses[command]


if __name__ == "__main__":
    unittest.main()
