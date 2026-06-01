import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tigerdiag.elm327 import ElmError
from tigerdiag.uds import (
    DiscoveredModule,
    classify_uds_response,
    decode_uds_dtc,
    discovered_modules_to_dict,
    module_profile_to_dict,
    parse_header_int,
    parse_uds_dtc_response,
    profile_from_discovery,
)


class UdsParsingTests(unittest.TestCase):
    def test_decode_uds_dtc_uses_sae_base_when_possible(self):
        item = decode_uds_dtc([0x01, 0x71, 0x00], 0x0C)
        self.assertEqual(item.code, "P0171-00")
        self.assertEqual(item.raw, "017100")
        self.assertEqual(item.status_flags, ["pending", "confirmed"])

    def test_parse_positive_response_skips_availability_mask(self):
        result = parse_uds_dtc_response(["7E8 07 59 02 FF 01 71 00 0C"], subfunction=0x02)
        self.assertEqual([item.code for item in result], ["P0171-00"])

    def test_parse_ignores_negative_response(self):
        result = parse_uds_dtc_response(["7E8 03 7F 19 12"], subfunction=0x02)
        self.assertEqual(result, [])

    def test_parse_multiframe_dtc_response(self):
        result = parse_uds_dtc_response(
            [
                "7E8 10 0B 59 02 FF 01 71 00",
                "7E8 21 0C 03 00 00 08 00 00",
            ],
            subfunction=0x02,
        )
        self.assertEqual([item.code for item in result], ["P0171-00", "P0300-00"])
        self.assertEqual(result[0].status_flags, ["pending", "confirmed"])

    def test_classify_positive_response(self):
        self.assertEqual(classify_uds_response(["7E8 07 59 02 FF 01 71 00 0C"]), "positive")

    def test_classify_negative_response(self):
        self.assertEqual(classify_uds_response(["7E8 03 7F 19 12"]), "negative_0x12")

    def test_parse_header_int_rejects_29_bit_header(self):
        with self.assertRaises(ElmError):
            parse_header_int("18DA10F1")

    def test_discovered_modules_to_dict(self):
        data = discovered_modules_to_dict(
            [
                DiscoveredModule(
                    tx_header="7E0",
                    response_kind="positive",
                    dtc_count=1,
                    raw_lines=["7E8 07 59 02 FF 01 71 00 0C"],
                )
            ]
        )
        self.assertEqual(data[0]["tx_header"], "7E0")
        self.assertEqual(data[0]["dtc_count"], 1)

    def test_profile_from_discovery_keeps_usable_responses(self):
        profile = profile_from_discovery(
            {
                "modules": [
                    {
                        "tx_header": "720",
                        "response_kind": "positive",
                        "dtc_count": 0,
                        "raw_lines": ["728 03 59 02 FF"],
                    },
                    {
                        "tx_header": "760",
                        "response_kind": "negative_0x12",
                        "dtc_count": 0,
                        "raw_lines": ["768 03 7F 19 12"],
                    },
                    {
                        "tx_header": "7E0",
                        "response_kind": "other",
                        "dtc_count": 0,
                        "raw_lines": ["noise"],
                    },
                ]
            },
            name="Generated",
        )

        self.assertEqual([item.tx_header for item in profile.modules], ["720", "760"])
        data = module_profile_to_dict(profile)
        self.assertEqual(data["name"], "Generated")
        self.assertEqual(len(data["modules"]), 2)

    def test_profile_from_discovery_rejects_no_usable_headers(self):
        with self.assertRaises(ElmError):
            profile_from_discovery({"modules": [{"tx_header": "7E0", "response_kind": "other"}]}, name="Generated")


if __name__ == "__main__":
    unittest.main()
