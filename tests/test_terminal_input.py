from __future__ import annotations

import unittest

from shot_dispenser.commands import Control
from shot_dispenser.terminal_input import parse_terminal_command


class TerminalInputTests(unittest.TestCase):
    def test_hold_command_emits_down_and_up_with_delay(self) -> None:
        action = parse_terminal_command("hold 1 2.5")

        self.assertEqual(2.5, action.delay_seconds)
        self.assertEqual(2, len(action.inputs))
        self.assertEqual(Control.PUMP_1, action.inputs[0].control)
        self.assertTrue(action.inputs[0].pressed)
        self.assertEqual(Control.PUMP_1, action.inputs[1].control)
        self.assertFalse(action.inputs[1].pressed)

    def test_down_and_up_commands(self) -> None:
        down = parse_terminal_command("all down")
        up = parse_terminal_command("all up")

        self.assertEqual(Control.ALL_PUMPS, down.inputs[0].control)
        self.assertTrue(down.inputs[0].pressed)
        self.assertEqual(Control.ALL_PUMPS, up.inputs[0].control)
        self.assertFalse(up.inputs[0].pressed)

    def test_momentary_command(self) -> None:
        action = parse_terminal_command("pvp")

        self.assertEqual(Control.PVP_START, action.inputs[0].control)
        self.assertTrue(action.inputs[0].pressed)

    def test_quit_command_stops_runner(self) -> None:
        action = parse_terminal_command("quit")

        self.assertTrue(action.stop_runner)

    def test_invalid_hold_target_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_terminal_command("hold pvp 1")


if __name__ == "__main__":
    unittest.main()
