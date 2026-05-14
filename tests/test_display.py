from __future__ import annotations

import unittest

from shot_dispenser.config import LcdConfig
from shot_dispenser.display import LcdDisplay


class FakeLcd:
    def __init__(self, fail_on_write: bool = False) -> None:
        self.fail_on_write = fail_on_write
        self.closed = False
        self.cursor_pos = (0, 0)
        self.writes: list[str] = []

    def clear(self) -> None:
        if self.fail_on_write:
            raise OSError("i2c write failed")

    def write_string(self, value: str) -> None:
        if self.fail_on_write:
            raise OSError("i2c write failed")
        self.writes.append(value)

    def close(self, clear: bool = False) -> None:
        self.closed = True


class LcdDisplayTest(unittest.TestCase):
    def test_startup_open_failure_does_not_raise(self) -> None:
        def broken_factory():
            raise OSError("i2c down")

        display = LcdDisplay(LcdConfig(), lcd_factory=broken_factory)

        display.show_lines("Ready")
        display.clear()
        display.reset()

    def test_write_failure_does_not_raise_and_next_write_reopens(self) -> None:
        lcds = [FakeLcd(fail_on_write=True), FakeLcd()]

        def factory():
            return lcds.pop(0)

        display = LcdDisplay(LcdConfig(), lcd_factory=factory)

        display.show_lines("first")
        display.show_lines("second")

        self.assertTrue(lcds == [])


if __name__ == "__main__":
    unittest.main()
