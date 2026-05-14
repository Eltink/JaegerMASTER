from __future__ import annotations

import unittest

from shot_dispenser.app import build_parser


class AppParserTests(unittest.TestCase):
    def test_pump_active_high_flag_is_supported(self) -> None:
        args = build_parser().parse_args(["--pump-active-high"])

        self.assertTrue(args.pump_active_high)
        self.assertFalse(args.pump_active_low)

    def test_pump_active_low_flag_is_supported(self) -> None:
        args = build_parser().parse_args(["--pump-active-low"])

        self.assertFalse(args.pump_active_high)
        self.assertTrue(args.pump_active_low)


if __name__ == "__main__":
    unittest.main()
