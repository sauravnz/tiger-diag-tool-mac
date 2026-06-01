import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tigerdiag.obd import hex_bytes, response_payload


class ObdParsingTests(unittest.TestCase):
    def test_hex_bytes_ignores_headers_with_three_digit_can_ids(self):
        self.assertEqual(hex_bytes("7E8 06 41 01 80 00 00 00"), [0x06, 0x41, 0x01, 0x80, 0x00, 0x00, 0x00])

    def test_response_payload_headerless_pid(self):
        payload = response_payload(["41 01 80 03 00 00"], expected_mode="41", pid="01")
        self.assertEqual(payload, [0x80, 0x03, 0x00, 0x00])

    def test_response_payload_headered_pid(self):
        payload = response_payload(["7E8 06 41 01 80 03 00 00"], expected_mode="41", pid="01")
        self.assertEqual(payload, [0x80, 0x03, 0x00, 0x00])

    def test_response_payload_dtc_mode(self):
        payload = response_payload(["43 01 71 03 00 00 00"], expected_mode="43")
        self.assertEqual(payload, [0x01, 0x71, 0x03, 0x00, 0x00, 0x00])

    def test_response_payload_multiframe_vin(self):
        payload = response_payload(
            [
                "7E8 10 14 49 02 01 53 4D 54",
                "7E8 21 54 52 45 58 41 4D 50",
                "7E8 22 4C 45 31 32 33 34 35",
            ],
            expected_mode="49",
            pid="02",
        )
        self.assertEqual(bytes(payload[1:]).decode("ascii"), "SMTTREXAMPLE12345")


if __name__ == "__main__":
    unittest.main()
