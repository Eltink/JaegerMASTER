from __future__ import annotations

import unittest

from shot_dispenser.config import AppConfig


class ConfigTests(unittest.TestCase):
    def test_pump_pins_follow_four_channel_relay_hat(self) -> None:
        config = AppConfig()

        self.assertEqual(config.gpio.pump_pins, (26, 19, 13, 6))
        self.assertFalse(config.gpio.pump_active_high)


if __name__ == "__main__":
    unittest.main()
