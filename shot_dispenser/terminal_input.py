from __future__ import annotations

import shlex
import sys
import time
from dataclasses import dataclass
from typing import Callable, TextIO

from .commands import Control, OperatorInput


HOLDABLE_CONTROLS = {
    Control.PUMP_1,
    Control.PUMP_2,
    Control.PUMP_3,
    Control.PUMP_4,
    Control.RANDOM_PUMP,
    Control.ALL_PUMPS,
    Control.LOTTERY,
}


CONTROL_ALIASES = {
    "1": Control.PUMP_1,
    "p1": Control.PUMP_1,
    "pump1": Control.PUMP_1,
    "2": Control.PUMP_2,
    "p2": Control.PUMP_2,
    "pump2": Control.PUMP_2,
    "3": Control.PUMP_3,
    "p3": Control.PUMP_3,
    "pump3": Control.PUMP_3,
    "4": Control.PUMP_4,
    "p4": Control.PUMP_4,
    "pump4": Control.PUMP_4,
    "5": Control.RANDOM_PUMP,
    "r": Control.RANDOM_PUMP,
    "random": Control.RANDOM_PUMP,
    "random-pump": Control.RANDOM_PUMP,
    "6": Control.ALL_PUMPS,
    "all": Control.ALL_PUMPS,
    "all-pumps": Control.ALL_PUMPS,
    "pump": Control.ALL_PUMPS,
    "pumps": Control.ALL_PUMPS,
    "+": Control.LOTTERY,
    "lottery": Control.LOTTERY,
    "sorteio": Control.LOTTERY,
    "7": Control.PLAYER_LEFT,
    "left": Control.PLAYER_LEFT,
    "left-player": Control.PLAYER_LEFT,
    "8": Control.PVP_START,
    "pvp": Control.PVP_START,
    "start": Control.PVP_START,
    "9": Control.PLAYER_RIGHT,
    "right": Control.PLAYER_RIGHT,
    "right-player": Control.PLAYER_RIGHT,
    "0": Control.STOP_ALL,
    "stop": Control.STOP_ALL,
    "safe-stop": Control.STOP_ALL,
}


@dataclass(frozen=True)
class TerminalAction:
    inputs: tuple[OperatorInput, ...] = ()
    delay_seconds: float = 0.0
    stop_runner: bool = False
    message: str | None = None


class TerminalInputRunner:
    def __init__(
        self,
        callback: Callable[[OperatorInput], None],
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        self._callback = callback
        self._input_stream = input_stream or sys.stdin
        self._output_stream = output_stream or sys.stdout

    def run_forever(self) -> None:
        self._write_help()
        for raw_line in self._input_stream:
            try:
                action = parse_terminal_command(raw_line)
            except ValueError as exc:
                self._write(f"Error: {exc}")
                continue

            if action.message:
                self._write(action.message)
            if action.stop_runner:
                return
            for index, operator_input in enumerate(action.inputs):
                if index and action.delay_seconds:
                    time.sleep(action.delay_seconds)
                self._callback(operator_input)

    def _write_help(self) -> None:
        self._write(
            "Terminal control ready. Examples: `hold 1 2`, `1 down`, `1 up`, "
            "`random down`, `random up`, `all down`, `all up`, `pvp`, `left`, "
            "`right`, `stop`, `quit`."
        )

    def _write(self, message: str) -> None:
        print(message, file=self._output_stream, flush=True)


def parse_terminal_command(raw_line: str) -> TerminalAction:
    parts = shlex.split(raw_line.strip().lower())
    if not parts:
        return TerminalAction()

    command = parts[0]
    if command in {"help", "h", "?"}:
        return TerminalAction(
            message=(
                "Commands: hold <1|2|3|4|random|all> <seconds>, "
                "<control> down, <control> up, pvp, left, right, stop, quit"
            )
        )
    if command in {"quit", "exit"}:
        return TerminalAction(stop_runner=True, message="Leaving terminal control.")

    if command == "hold":
        if len(parts) != 3:
            raise ValueError("Use `hold <1|2|3|4|random|all> <seconds>`.")
        control = _parse_control(parts[1])
        if control not in HOLDABLE_CONTROLS:
            raise ValueError(f"{parts[1]!r} is not a hold-to-run control.")
        delay_seconds = _parse_positive_seconds(parts[2])
        return TerminalAction(
            inputs=(
                OperatorInput(control, pressed=True),
                OperatorInput(control, pressed=False),
            ),
            delay_seconds=delay_seconds,
        )

    control = _parse_control(command)
    if control in HOLDABLE_CONTROLS:
        if len(parts) != 2 or parts[1] not in {"down", "press", "on", "up", "release", "off"}:
            raise ValueError(
                f"Use `{command} down`, `{command} up`, or `hold {command} <seconds>`."
            )
        pressed = parts[1] in {"down", "press", "on"}
        return TerminalAction(inputs=(OperatorInput(control, pressed=pressed),))

    if len(parts) != 1:
        raise ValueError(f"{command!r} does not take extra arguments.")
    return TerminalAction(inputs=(OperatorInput(control, pressed=True),))


def _parse_control(value: str) -> Control:
    try:
        return CONTROL_ALIASES[value]
    except KeyError as exc:
        raise ValueError(f"Unknown control {value!r}. Type `help` for commands.") from exc


def _parse_positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ValueError(f"Seconds must be a number, got {value!r}.") from exc
    if seconds <= 0:
        raise ValueError("Seconds must be greater than zero.")
    return seconds
