from __future__ import annotations

import argparse
import atexit
import signal
import subprocess
import threading
import time
from collections.abc import Callable

from .commands import Control, OperatorInput
from .config import AppConfig, GpioPins, LcdConfig, NumpadConfig, parse_lcd_address
from .controller import ShotDispenserController
from .display import ConsoleDisplay, LcdDisplay
from .hardware import FakeHardware, GpioHardware
from .messages import DEFAULT_MESSAGES
from .numpad import EvdevNumpadInput, NumpadKeyMapper, list_input_devices
from .terminal_input import TerminalInputRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Raspberry Pi shot dispenser with Bluetooth numpad input."
    )
    parser.add_argument(
        "--list-input-devices",
        action="store_true",
        help="List Linux input devices and exit. Use this to find the numpad path.",
    )
    parser.add_argument(
        "--numpad-device",
        help="Explicit /dev/input/event* path for the Bluetooth numpad.",
    )
    parser.add_argument(
        "--numpad-name",
        help="Only auto-select a numpad whose device name contains this text.",
    )
    parser.add_argument(
        "--no-input-grab",
        action="store_true",
        help="Do not exclusively grab the numpad input device.",
    )
    parser.add_argument(
        "--lcd-address",
        default="0x27",
        help="I2C LCD address, for example 0x27 or 0x3f.",
    )
    parser.add_argument("--lcd-columns", type=int, default=20)
    parser.add_argument("--lcd-rows", type=int, default=4)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use console output and fake hardware. Still reads numpad events.",
    )
    parser.add_argument(
        "--terminal-control",
        action="store_true",
        help="Read explicit test commands from the terminal instead of an input device.",
    )
    parser.add_argument(
        "--shutdown-command",
        nargs=argparse.REMAINDER,
        help=(
            "Command to run after the operator shutdown chord. Put this last, "
            "for example: --shutdown-command sudo -n /usr/sbin/poweroff"
        ),
    )
    parser.add_argument(
        "--restart-command",
        nargs=argparse.REMAINDER,
        help=(
            "Command to run after the operator restart chord. Put this last, "
            "for example: --restart-command sudo -n /usr/sbin/reboot"
        ),
    )
    pump_polarity = parser.add_mutually_exclusive_group()
    pump_polarity.add_argument(
        "--pump-active-high",
        action="store_true",
        help="Use for temporary relay modules where GPIO HIGH turns a pump relay on.",
    )
    pump_polarity.add_argument(
        "--pump-active-low",
        action="store_true",
        help="Use for relay HATs/modules where GPIO LOW turns a pump relay on.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_input_devices:
        return _print_input_devices()

    lcd_config = LcdConfig(
        address=parse_lcd_address(args.lcd_address),
        columns=args.lcd_columns,
        rows=args.lcd_rows,
    )
    numpad_config = NumpadConfig(
        device_path=args.numpad_device,
        device_name_contains=args.numpad_name,
        grab_input=not args.no_input_grab,
    )
    gpio_config = GpioPins()
    if args.pump_active_high:
        gpio_config = GpioPins(pump_active_high=True)
    elif args.pump_active_low:
        gpio_config = GpioPins(pump_active_high=False)
    config = AppConfig(gpio=gpio_config, lcd=lcd_config, numpad=numpad_config)

    hardware = FakeHardware() if args.dry_run else GpioHardware(config.gpio)
    display = (
        ConsoleDisplay(columns=config.lcd.columns, rows=config.lcd.rows)
        if args.dry_run
        else LcdDisplay(config.lcd)
    )
    controller = ShotDispenserController(
        hardware=hardware,
        display=display,
        timing=config.timing,
        messages=DEFAULT_MESSAGES,
        pump_count=config.gpio.pump_count,
    )
    stop_event = threading.Event()
    shutdown_once = _make_shutdown_once(controller, stop_event)
    _install_signal_handlers(shutdown_once)
    atexit.register(shutdown_once, "process exit")

    handle_input = _make_input_handler(
        controller,
        display,
        shutdown_once,
        args.shutdown_command,
        args.restart_command,
    )

    try:
        if args.terminal_control:
            _run_boot_screen(display, config.timing.boot_seconds)
            controller.show_ready()
            TerminalInputRunner(handle_input).run_forever()
        else:
            mapper = NumpadKeyMapper(
                config.numpad.key_bindings,
                config.numpad.shutdown_chord,
                config.numpad.restart_chord,
            )
            numpad = EvdevNumpadInput(config.numpad, mapper, handle_input)

            # Start numpad in a thread so keys work during boot screen.
            input_thread = threading.Thread(
                target=numpad.run_forever,
                args=(stop_event,),
                name="numpad-input",
                daemon=True,
            )
            input_thread.start()
            _run_boot_screen(display, config.timing.boot_seconds)
            controller.show_ready()
            input_thread.join()

    except KeyboardInterrupt:
        shutdown_once("keyboard interrupt")
        return 0
    except RuntimeError as exc:
        shutdown_once("input error")
        display.show_lines(
            DEFAULT_MESSAGES.title,
            DEFAULT_MESSAGES.input_error,
            str(exc)[: display.columns],
        )
        raise
    return 0


def _run_boot_screen(display, duration: float) -> None:
    msgs = DEFAULT_MESSAGES
    credits = msgs.boot_credits
    cols = display.columns
    padded = credits + " " * cols
    start = time.monotonic()
    pos = 0
    while time.monotonic() - start < duration:
        window = (padded * 2)[pos: pos + cols]
        display.show_lines(msgs.main_line1, msgs.main_line2, msgs.main_line3, window)
        pos = (pos + 1) % len(padded)
        time.sleep(0.15)


def _make_input_handler(
    controller: ShotDispenserController,
    display,
    shutdown_once: Callable[[str], None],
    shutdown_command: list[str] | None = None,
    restart_command: list[str] | None = None,
) -> Callable[[OperatorInput], None]:
    def handle_input(operator_input: OperatorInput) -> None:
        if operator_input.control is Control.SHUTDOWN:
            if operator_input.pressed:
                _do_operator_shutdown(controller, display, shutdown_once, shutdown_command)
            return
        if operator_input.control is Control.RESTART:
            if operator_input.pressed:
                _do_operator_shutdown(controller, display, shutdown_once, restart_command)
            return
        controller.handle_input(operator_input)

    return handle_input


def _do_operator_shutdown(
    controller: ShotDispenserController,
    display,
    shutdown_once: Callable[[str], None],
    command: list[str] | None,
) -> None:
    controller.safe_stop("operator")
    display.show_lines(DEFAULT_MESSAGES.shutdown_message, "", "", "")
    time.sleep(1.5)
    display.backlight_off()
    shutdown_once("operator shutdown")
    _run_shutdown_command(command)


def _run_shutdown_command(command: list[str] | None) -> None:
    if not command:
        return
    subprocess.Popen(command)


def _print_input_devices() -> int:
    devices = list_input_devices()
    if not devices:
        print("No Linux input devices are visible.")
        return 1

    for device in devices:
        print(f"{device.path}: {device.name} ({device.physical_location})")
        keypad_keys = [key for key in device.supported_keys if key.startswith("KEY_KP")]
        if keypad_keys:
            print(f"  keypad keys: {', '.join(keypad_keys)}")
    return 0


def _make_shutdown_once(
    controller: ShotDispenserController,
    stop_event: threading.Event,
) -> Callable[[str], None]:
    lock = threading.Lock()
    completed = False

    def shutdown(reason: str) -> None:
        nonlocal completed
        with lock:
            if completed:
                return
            completed = True
            stop_event.set()
        controller.shutdown(reason)

    return shutdown


def _install_signal_handlers(shutdown_once: Callable[[str], None]) -> None:
    def handle_signal(signum, _frame) -> None:
        try:
            reason = signal.Signals(signum).name.lower()
        except ValueError:
            reason = f"signal {signum}"
        shutdown_once(reason)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
