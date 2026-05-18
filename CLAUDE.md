# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Raspberry Pi 4 shot dispenser firmware. The canonical app is `main.py`, backed by the `shot_dispenser/` package. It drives four independent drink pumps, a traffic-light LED set, a 20x4 I2C LCD, and a standard HID keyboard/numpad via Linux `evdev` input events.

The old flat scripts are still present for reference and hardware bring-up, but they use the older valve/shared-pump model:

| Script | Purpose |
|---|---|
| `Alles_Dabei.py` | Legacy full version with GPIO buttons |
| `Pumpe_und_Ventile.py` | Legacy dispenser-only GPIO-button bring-up |
| `ventil_toggle.py` | Single valve/pump wiring check with a different pin map |

## Running

Dependencies on the Pi:

```bash
sudo apt install python3-gpiozero python3-smbus i2c-tools python3-evdev -y
pip install RPLCD --break-system-packages
sudo raspi-config   # Interface Options -> I2C -> Enable
i2cdetect -y 1      # confirm LCD address, usually 0x27 or 0x3f
```

Run:

```bash
python3 main.py --list-input-devices
python3 main.py --numpad-device /dev/input/eventX
python3 main.py --numpad-name Logitech
python3 main.py --dry-run --numpad-device /dev/input/eventX
python3 main.py --terminal-control  # explicit SSH/terminal bench-test commands
```

Off-Pi validation:

```bash
python3 -m py_compile main.py Alles_Dabei.py Pumpe_und_Ventile.py ventil_toggle.py shot_dispenser/*.py tests/*.py
python3 -m unittest discover -s tests
python3 -m unittest tests.test_controller.ControllerTests.test_pvp_right_player_wins_blinks_red
```

There is no configured lint command.

## Architecture

`main.py` is a thin entry point. Keep implementation in package modules:

- `app.py`: CLI parsing and adapter wiring
- `config.py`: pump GPIO, LCD, timing, and numpad binding defaults
- `controller.py`: pump control, random pump rotation, all-pumps action, PvP state machine, safe stop, concurrency guard
- `hardware.py`: real GPIO adapter and fake hardware
- `display.py`: LCD adapter and console/fake display
- `numpad.py`: `evdev` discovery and key event mapping
- `events.py`: event-publisher boundary for future web server calls
- `messages.py`: LCD/operator strings

## Shared invariants

- Numpad events use Linux `EV_KEY`: value `1` is key down, `0` is key up, and `2` is repeat. Repeat events should not start duplicate actions.
- Default mapping: KP1-KP4 Pump 1-4, KP5 random pump, KP6 all pumps, KP7 PvP start/restart, KP8 left player, KP9 right player, KP0/KP Enter safe stop.
- Pump relay outputs follow the 4-channel Raspberry Pi relay HAT pinout: CH1 GPIO26, CH2 GPIO19, CH3 GPIO13, CH4 GPIO6.
- Only one hardware-driving action should run at a time. Single pump, random pump, all-pumps, and PvP actions all go through `ShotDispenserController`.
- Relay outputs are active-low and must initialize inactive/off.
- Random pump selection drains a shuffled pool of all four pumps before any pump repeats.
- Future web server calls belong behind `EventPublisher`; do not couple HTTP directly into hardware control.
