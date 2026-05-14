# Copilot instructions for JaegerMASTER

## Project context

This repository contains Raspberry Pi 4 firmware for a four-pump shot dispenser. The canonical app is `main.py`, which delegates to the `shot_dispenser/` package and uses a standard HID keyboard/numpad through Linux `evdev` input events. GPIO/LCD entry points require Raspberry Pi hardware; off-device work should use syntax checks, unit tests, and fake adapters.

The current canonical hardware model is four independent drink pumps, one hose per drink. The old flat scripts remain only for reference and hardware bring-up: `Alles_Dabei.py` is the legacy full GPIO-button version, `Pumpe_und_Ventile.py` is dispenser-only, and `ventil_toggle.py` is a single valve/pump wiring check with a different pin map. Do not copy the old valve/shared-pump model into the canonical package.

## Commands

Pi setup:

```bash
sudo apt update
sudo apt install python3-gpiozero python3-smbus i2c-tools python3-evdev -y
pip install RPLCD --break-system-packages
sudo raspi-config   # Interface Options -> I2C -> Enable
i2cdetect -y 1      # verify LCD address, usually 0x27 or 0x3f
```

Run on the Pi:

```bash
python3 main.py --list-input-devices
python3 main.py --numpad-device /dev/input/eventX
python3 main.py --numpad-name Logitech
python3 main.py --dry-run --numpad-device /dev/input/eventX
python3 main.py --terminal-control
```

Validation off the Pi:

```bash
python3 -m py_compile main.py Alles_Dabei.py Pumpe_und_Ventile.py ventil_toggle.py shot_dispenser/*.py tests/*.py
python3 -m unittest discover -s tests
python3 -m unittest tests.test_controller.ControllerTests.test_pvp_right_player_wins_after_green
```

There is no configured lint command.

## Architecture

`main.py` is intentionally thin. Keep behavior in package modules:

- `app.py`: CLI parsing, startup/shutdown, wiring hardware/display/input adapters
- `config.py`: pump GPIO pins, LCD settings, timings, and key bindings
- `controller.py`: pump control, random pump pool, all-pumps action, PvP state machine, concurrency guard, safe stop
- `hardware.py`: real GPIO adapter and fake hardware
- `display.py`: real LCD adapter and console/fake display
- `numpad.py`: `evdev` device discovery and key-down/key-up mapping
- `events.py`: future web-server event boundary; do not add HTTP calls until API specs/schemas/auth/offline behavior are known
- `messages.py`: operator-facing LCD strings

The controller owns hardware safety. Only one pump/random/all-pumps/PvP action should run at a time. Hold-to-run actions start on key-down and stop on key-up; repeat value `2` from Linux `EV_KEY` events is ignored.

## Codebase conventions

- Default numpad mapping is KP1-KP4 for Pump 1-4, KP5 random pump, KP6 all pumps, KP7 PvP start/restart, KP8 left player, KP9 right player, KP0/KP Enter safe stop.
- Pump relay outputs follow the 4-channel Raspberry Pi relay HAT pinout: CH1 GPIO26, CH2 GPIO19, CH3 GPIO13, CH4 GPIO6. The HAT is active-low, so use `OutputDevice(..., active_high=False, initial_value=False)` to keep pumps off at startup.
- GPIO17 is not used by the canonical package; it belonged to the old shared-pump model.
- Random pump selection uses a shuffled pool that drains before reshuffling; do not replace it with unconstrained random selection.
- Display writes go through the display adapter and should stay fixed-width for the configured LCD columns/rows.
- Avoid GPIO0, GPIO1, GPIO11, and GPIO24. GPIO2/GPIO3 are reserved for I2C display wiring. GPIO26/GPIO19/GPIO13/GPIO6 are reserved for the relay HAT pump channels.
- Keep future web integration behind `EventPublisher`; hardware control should not depend directly on HTTP client code.
