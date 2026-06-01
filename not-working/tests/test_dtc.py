import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tigerdiag.dtc import decode_dtc_bytes, decode_dtc_pair


class DtcTests(unittest.TestCase):
    def test_decode_powertrain_code(self):
        self.assertEqual(decode_dtc_pair(0x01, 0x71), "P0171")

    def test_decode_chassis_code(self):
        self.assertEqual(decode_dtc_pair(0x41, 0x00), "C0100")

    def test_zero_pair_is_padding(self):
        self.assertIsNone(decode_dtc_pair(0x00, 0x00))

    def test_decode_multiple_codes_skips_padding(self):
        codes = decode_dtc_bytes([0x01, 0x71, 0x03, 0x00, 0x00, 0x00])
        self.assertEqual([item.code for item in codes], ["P0171", "P0300"])


if __name__ == "__main__":
    unittest.main()
