import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tigerdiag.isotp import parse_can_line, reassemble_isotp_payloads


class IsoTpTests(unittest.TestCase):
    def test_parse_can_line_with_header(self):
        self.assertEqual(parse_can_line("7E8 06 41 01 80 00 00 00"), ("7E8", [0x06, 0x41, 0x01, 0x80, 0x00, 0x00, 0x00]))

    def test_reassemble_single_frame(self):
        payloads = reassemble_isotp_payloads(["7E8 06 41 01 80 00 00 00"])
        self.assertEqual(payloads, [[0x41, 0x01, 0x80, 0x00, 0x00, 0x00]])

    def test_reassemble_multi_frame(self):
        payloads = reassemble_isotp_payloads(
            [
                "7E8 10 0B 59 02 FF 01 71 00",
                "7E8 21 0C 03 00 00 08 00 00",
            ]
        )
        self.assertEqual(payloads, [[0x59, 0x02, 0xFF, 0x01, 0x71, 0x00, 0x0C, 0x03, 0x00, 0x00, 0x08]])

    def test_reassemble_headerless_multi_frame(self):
        payloads = reassemble_isotp_payloads(
            [
                "10 09 49 02 01 53 4D 54",
                "21 54 52 45 00 00 00 00",
            ]
        )
        self.assertEqual(payloads, [[0x49, 0x02, 0x01, 0x53, 0x4D, 0x54, 0x54, 0x52, 0x45]])


if __name__ == "__main__":
    unittest.main()
