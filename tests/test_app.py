from __future__ import annotations

import unittest
from unittest.mock import patch

from shot_dispenser.app import _make_input_handler, build_parser
from shot_dispenser.commands import Control, OperatorInput
from shot_dispenser.display import ConsoleDisplay


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

    def test_restart_command_captures_remaining_args(self) -> None:
        args = build_parser().parse_args([
            "--restart-command",
            "sudo",
            "-n",
            "/usr/sbin/reboot",
        ])

        self.assertEqual(["sudo", "-n", "/usr/sbin/reboot"], args.restart_command)


class AppInputHandlerTests(unittest.TestCase):
    def _make_handler(self, controller, shutdown_once=None, shutdown_cmd=None, restart_cmd=None):
        display = ConsoleDisplay()
        return _make_input_handler(
            controller,
            display,
            shutdown_once or (lambda _reason: None),
            shutdown_cmd,
            restart_cmd,
        )

    def test_shutdown_control_runs_shutdown_once(self) -> None:
        controller = FakeController()
        shutdown_reasons: list[str] = []

        with patch("shot_dispenser.app.time.sleep"):
            handler = self._make_handler(controller, shutdown_reasons.append)
            handler(OperatorInput(Control.SHUTDOWN, pressed=True))
            handler(OperatorInput(Control.SHUTDOWN, pressed=False))

        self.assertEqual(["operator shutdown"], shutdown_reasons)
        self.assertEqual([], controller.inputs)

    def test_shutdown_control_runs_configured_poweroff_command(self) -> None:
        controller = FakeController()

        with patch("shot_dispenser.app.subprocess.Popen") as popen, \
             patch("shot_dispenser.app.time.sleep"):
            handler = self._make_handler(
                controller,
                shutdown_cmd=["sudo", "-n", "/usr/sbin/poweroff"],
            )
            handler(OperatorInput(Control.SHUTDOWN, pressed=True))

        popen.assert_called_once_with(["sudo", "-n", "/usr/sbin/poweroff"])

    def test_restart_control_runs_configured_restart_command(self) -> None:
        controller = FakeController()

        with patch("shot_dispenser.app.subprocess.Popen") as popen, \
             patch("shot_dispenser.app.time.sleep"):
            handler = self._make_handler(
                controller,
                restart_cmd=["sudo", "-n", "/usr/sbin/reboot"],
            )
            handler(OperatorInput(Control.RESTART, pressed=True))

        popen.assert_called_once_with(["sudo", "-n", "/usr/sbin/reboot"])

    def test_other_controls_are_forwarded_to_controller(self) -> None:
        controller = FakeController()
        handler = self._make_handler(controller)
        operator_input = OperatorInput(Control.STOP_ALL, pressed=True)

        handler(operator_input)

        self.assertEqual([operator_input], controller.inputs)


class FakeController:
    def __init__(self) -> None:
        self.inputs: list[OperatorInput] = []

    def handle_input(self, operator_input: OperatorInput) -> None:
        self.inputs.append(operator_input)

    def safe_stop(self, reason: str) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
