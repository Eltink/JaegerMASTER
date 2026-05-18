from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

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

    def reset(self) -> None:
        ...

    def set_backlight(self, on: bool) -> None:
        ...


class LcdDisplay:
    def __init__(
        self,
        config: LcdConfig,
        lcd_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.columns = config.columns
        self.rows = config.rows
        self._config = config
        self._lcd_factory = lcd_factory
        self._lock = threading.Lock()
        self._lcd = None
        self._last_error: str | None = None
        self.reset()

    def _open_lcd(self):
        if self._lcd_factory is not None:
            return self._lcd_factory()

        from RPLCD.i2c import CharLCD

        return CharLCD(
            i2c_expander="PCF8574",
            address=self._config.address,
            port=self._config.port,
            cols=self._config.columns,
            rows=self._config.rows,
            dotsize=self._config.dotsize,
        )

    def show_lines(self, *lines: str) -> None:
        normalized = list(lines[: self.rows])
        normalized.extend("" for _ in range(self.rows - len(normalized)))

        with self._lock:
            lcd = self._get_lcd()
            if lcd is None:
                return
            try:
                lcd.clear()
                for row, line in enumerate(normalized):
                    lcd.cursor_pos = (row, 0)
                    lcd.write_string(line[: self.columns])
            except OSError as exc:
                self._mark_lcd_failed("write", lcd, exc)

    def clear(self) -> None:
        with self._lock:
            lcd = self._get_lcd()
            if lcd is None:
                return
            try:
                lcd.clear()
            except OSError as exc:
                self._mark_lcd_failed("clear", lcd, exc)

    def reset(self) -> None:
        with self._lock:
            old_lcd = self._lcd
            self._lcd = self._try_open_lcd()
            self._close_lcd(old_lcd)

    def set_backlight(self, on: bool) -> None:
        with self._lock:
            lcd = self._get_lcd()
            if lcd is None:
                return
            try:
                lcd.backlight_enabled = on
            except (OSError, AttributeError) as exc:
                if isinstance(exc, OSError):
                    self._mark_lcd_failed("backlight", lcd, exc)

    def _get_lcd(self):
        if self._lcd is None:
            self._lcd = self._try_open_lcd()
        return self._lcd

    def _try_open_lcd(self):
        try:
            lcd = self._open_lcd()
        except OSError as exc:
            self._report_error("open", exc)
            return None
        self._last_error = None
        return lcd

    def _mark_lcd_failed(self, action: str, lcd, exc: OSError) -> None:
        if self._lcd is lcd:
            self._lcd = None
        self._close_lcd(lcd)
        self._report_error(action, exc)

    def _report_error(self, action: str, exc: OSError) -> None:
        message = f"LCD {action} failed: {exc}"
        if message == self._last_error:
            return
        self._last_error = message
        print(message)

    def _close_lcd(self, lcd) -> None:
        if lcd is None:
            return
        close = getattr(lcd, "close", None)
        if close is None:
            return
        try:
            close(clear=False)
        except TypeError:
            try:
                close()
            except OSError:
                pass
        except OSError:
            pass


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

    def reset(self) -> None:
        with self._lock:
            self.history.append(("<reset>",))
        print("LCD: <reset>")

    def set_backlight(self, on: bool) -> None:
        print(f"LCD: <backlight {'on' if on else 'off'}>")
