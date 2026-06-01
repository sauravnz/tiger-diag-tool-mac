import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tigerdiag.elm327 import ElmError
from tigerdiag.service import (
    ServiceCommand,
    ServiceProfile,
    dry_run_profile,
    parse_variable_assignments,
    render_profile,
)


class ServiceProfileTests(unittest.TestCase):
    def test_render_profile_variables(self):
        profile = ServiceProfile(
            name="test",
            description="date {next_service_date}",
            protocol="can_11_500",
            variables={"distance_km": "10000"},
            commands=[
                ServiceCommand(
                    command="2E F1 99 {distance_km}",
                    expect="6E F1 99",
                    note="date {next_service_date}",
                )
            ],
        )

        rendered = render_profile(profile, {"next_service_date": "2026-10-01"})

        self.assertEqual(rendered.description, "date 2026-10-01")
        self.assertEqual(rendered.commands[0].command, "2E F1 99 10000")
        self.assertEqual(rendered.commands[0].note, "date 2026-10-01")

    def test_render_profile_missing_variable(self):
        profile = ServiceProfile(
            name="test",
            description="{missing}",
            protocol="auto",
            variables={},
            commands=[],
        )

        with self.assertRaises(ElmError):
            render_profile(profile)

    def test_parse_variable_assignments(self):
        self.assertEqual(
            parse_variable_assignments(["next_service_date=2026-10-01", "distance_km=10000"]),
            {"next_service_date": "2026-10-01", "distance_km": "10000"},
        )

    def test_dry_run_profile_empty_commands(self):
        profile = ServiceProfile(
            name="empty",
            description="",
            protocol="auto",
            variables={},
            commands=[],
        )

        lines = dry_run_profile(profile)

        self.assertIn("commands:", lines)
        self.assertIn("  none", lines)


if __name__ == "__main__":
    unittest.main()

