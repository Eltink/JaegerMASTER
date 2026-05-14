from __future__ import annotations

import threading

try:
    from typing import Protocol
except ImportError:  # Python < 3.8
    class Protocol:  # type: ignore[no-redef]
        pass

from .config import LcdConfig


class Display(Protocol):
    columns: int
    rows: int

    def show_lines(self, *lines: str) -> None:
        ...

    def clear(self) -> None:
        ...


class LcdDisplay:
    def __init__(self, config: LcdConfig) -> None:
        from RPLCD.i2c import CharLCD

        self.columns = config.columns
        self.rows = config.rows
        self._lock = threading.Lock()
        self._lcd = CharLCD(
            i2c_expander="PCF8574",
            address=config.address,
            port=config.port,
            cols=config.columns,
            rows=config.rows,
            dotsize=config.dotsize,
        )

    def show_lines(self, *lines: str) -> None:
        normalized = list(lines[: self.rows])
        normalized.extend("" for _ in range(self.rows - len(normalized)))

        with self._lock:
            self._lcd.clear()
            for row, line in enumerate(normalized):
                self._lcd.cursor_pos = (row, 0)
                self._lcd.write_string(line[: self.columns])

    def clear(self) -> None:
        with self._lock:
            self._lcd.clear()


class ConsoleDisplay:
    def __init__(self, columns: int = 20, rows: int = 4) -> None:
        self.columns = columns
        self.rows = rows
        self.history: list[tuple[str, ...]] = []
        self._lock = threading.Lock()

    def show_lines(self, *lines: str) -> None:
        normalized = tuple(line[: self.columns] for line in lines[: self.rows])
        with self._lock:
            self.history.append(normalized)
        print("LCD:", " | ".join(normalized))

    def clear(self) -> None:
        with self._lock:
            self.history.append(())
        print("LCD: <clear>")
