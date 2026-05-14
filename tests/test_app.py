from __future__ import annotations

import unittest
from unittest.mock import patch

from shot_dispenser.app import _make_input_handler, build_parser
from shot_dispenser.commands import Control, OperatorInput


class AppParserTests(unittest.TestCase):
    def test_pump_active_high_flag_is_supported(self) -> None:
        args = build_parser().parse_args(["--pump-active-high"])

        self.assertTrue(args.pump_active_high)
        self.assertFalse(args.pump_active_low)

    def test_pump_active_low_flag_is_supported(self) -> None:
        args = build_parser().parse_args(["--pump-active-low"])

        self.assertFalse(args.pump_active_high)
        self.assertTrue(args.pump_active_low)

    def test_shutdown_command_captures_remaining_args(self) -> None:
        args = build_parser().parse_args([
            "--pump-active-high",
            "--shutdown-command",
            "sudo",
            "-n",
            "/usr/sbin/poweroff",
        ])

        self.assertEqual(["sudo", "-n", "/usr/sbin/poweroff"], args.shutdown_command)


class AppInputHandlerTests(unittest.TestCase):
    def test_shutdown_control_runs_shutdown_once(self) -> None:
        controller = FakeController()
        shutdown_reasons: list[str] = []
        handler = _make_input_handler(controller, shutdown_reasons.append)

        handler(OperatorInput(Control.SHUTDOWN, pressed=True))
        handler(OperatorInput(Control.SHUTDOWN, pressed=False))

        self.assertEqual(["operator shutdown"], shutdown_reasons)
        self.assertEqual([], controller.inputs)

    def test_shutdown_control_runs_configured_poweroff_command(self) -> None:
        controller = FakeController()
        handler = _make_input_handler(
            controller,
            lambda _reason: None,
            ["sudo", "-n", "/usr/sbin/poweroff"],
        )

        with patch("shot_dispenser.app.subprocess.Popen") as popen:
            handler(OperatorInput(Control.SHUTDOWN, pressed=True))

        popen.assert_called_once_with(["sudo", "-n", "/usr/sbin/poweroff"])

    def test_other_controls_are_forwarded_to_controller(self) -> None:
        controller = FakeController()
        handler = _make_input_handler(controller, lambda _reason: None)
        operator_input = OperatorInput(Control.STOP_ALL, pressed=True)

        handler(operator_input)

        self.assertEqual([operator_input], controller.inputs)


class FakeController:
    def __init__(self) -> None:
        self.inputs: list[OperatorInput] = []

    def handle_input(self, operator_input: OperatorInput) -> None:
        self.inputs.append(operator_input)


if __name__ == "__main__":
    unittest.main()
