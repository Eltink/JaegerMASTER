from __future__ import annotations

import time

try:
    from typing import Protocol
except ImportError:  # Python < 3.8
    class Protocol:  # type: ignore[no-redef]
        pass

from .config import GpioPins


class DispenserHardware(Protocol):
    def pump_on(self, pump_number: int) -> None:
        ...

    def pump_off(self, pump_number: int) -> None:
        ...

    def all_pumps_on(self) -> None:
        ...

    def all_pumps_off(self) -> None:
        ...

    def red_on(self) -> None:
        ...

    def yellow_on(self) -> None:
        ...

    def green_on(self) -> None:
        ...

    def red_off(self) -> None:
        ...

    def yellow_off(self) -> None:
        ...

    def green_off(self) -> None:
        ...

    def traffic_light_off(self) -> None:
        ...

    def blink_yellow(self, count: int, seconds: float) -> None:
        ...

    def blink_red(self, count: int, seconds: float) -> None:
        ...

    def blink_green(self, count: int, seconds: float) -> None:
        ...

    def all_off(self) -> None:
        ...


class GpioHardware:
    def __init__(self, pins: GpioPins) -> None:
        from gpiozero import LED, OutputDevice

        self._pumps = [
            OutputDevice(pin, active_high=pins.pump_active_high, initial_value=False)
            for pin in pins.pump_pins
        ]
        self._red = LED(pins.led_red_pin)
        self._yellow = LED(pins.led_yellow_pin)
        self._green = LED(pins.led_green_pin)

    def pump_on(self, pump_number: int) -> None:
        self._pumps[_index(pump_number)].on()

    def pump_off(self, pump_number: int) -> None:
        self._pumps[_index(pump_number)].off()

    def all_pumps_on(self) -> None:
        for pump_number in range(1, len(self._pumps) + 1):
            self.pump_on(pump_number)

    def all_pumps_off(self) -> None:
        for pump_number in range(1, len(self._pumps) + 1):
            self.pump_off(pump_number)

    def red_on(self) -> None:
        self._red.on()

    def yellow_on(self) -> None:
        self._yellow.on()

    def green_on(self) -> None:
        self._green.on()

    def red_off(self) -> None:
        self._red.off()

    def yellow_off(self) -> None:
        self._yellow.off()

    def green_off(self) -> None:
        self._green.off()

    def traffic_light_off(self) -> None:
        self.red_off()
        self.yellow_off()
        self.green_off()

    def blink_yellow(self, count: int, seconds: float) -> None:
        for _ in range(count):
            self.yellow_on()
            time.sleep(seconds)
            self.yellow_off()
            time.sleep(seconds)

    def blink_red(self, count: int, seconds: float) -> None:
        for _ in range(count):
            self.red_on()
            time.sleep(seconds)
            self.red_off()
            time.sleep(seconds)

    def blink_green(self, count: int, seconds: float) -> None:
        for _ in range(count):
            self.green_on()
            time.sleep(seconds)
            self.green_off()
            time.sleep(seconds)

    def all_off(self) -> None:
        self.all_pumps_off()
        self.traffic_light_off()


class FakeHardware:
    def __init__(self, pump_count: int = 4) -> None:
        self.pumps = [False] * pump_count
        self.red = False
        self.yellow = False
        self.green = False
        self.log: list[str] = []

    def pump_on(self, pump_number: int) -> None:
        self.pumps[_index(pump_number)] = True
        self.log.append(f"pump_{pump_number}_on")

    def pump_off(self, pump_number: int) -> None:
        self.pumps[_index(pump_number)] = False
        self.log.append(f"pump_{pump_number}_off")

    def all_pumps_on(self) -> None:
        for pump_number in range(1, len(self.pumps) + 1):
            self.pump_on(pump_number)

    def all_pumps_off(self) -> None:
        for pump_number in range(1, len(self.pumps) + 1):
            self.pump_off(pump_number)

    def red_on(self) -> None:
        self.red = True
        self.log.append("red_on")

    def yellow_on(self) -> None:
        self.yellow = True
        self.log.append("yellow_on")

    def green_on(self) -> None:
        self.green = True
        self.log.append("green_on")

    def red_off(self) -> None:
        self.red = False
        self.log.append("red_off")

    def yellow_off(self) -> None:
        self.yellow = False
        self.log.append("yellow_off")

    def green_off(self) -> None:
        self.green = False
        self.log.append("green_off")

    def traffic_light_off(self) -> None:
        self.red_off()
        self.yellow_off()
        self.green_off()

    def blink_yellow(self, count: int, seconds: float) -> None:
        for _ in range(count):
            self.yellow_on()
            if seconds:
                time.sleep(seconds)
            self.yellow_off()
            if seconds:
                time.sleep(seconds)

    def blink_red(self, count: int, seconds: float) -> None:
        for _ in range(count):
            self.red_on()
            if seconds:
                time.sleep(seconds)
            self.red_off()
            if seconds:
                time.sleep(seconds)

    def blink_green(self, count: int, seconds: float) -> None:
        for _ in range(count):
            self.green_on()
            if seconds:
                time.sleep(seconds)
            self.green_off()
            if seconds:
                time.sleep(seconds)

    def all_off(self) -> None:
        self.all_pumps_off()
        self.traffic_light_off()


def _index(pump_number: int) -> int:
    if pump_number < 1:
        raise ValueError(f"Pump numbers start at 1, got {pump_number}")
    return pump_number - 1
