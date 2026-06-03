from __future__ import annotations

from dataclasses import dataclass, field

from .commands import Control


@dataclass(frozen=True)
class GpioPins:
    pump_pins: tuple[int, int, int, int] = (26, 19, 13, 6)
    pump_active_high: bool = False
    led_red_pin: int = 16
    led_yellow_pin: int = 20
    led_green_pin: int = 21

    @property
    def pump_count(self) -> int:
        return len(self.pump_pins)


@dataclass(frozen=True)
class LcdConfig:
    address: int = 0x27
    port: int = 1
    columns: int = 20
    rows: int = 4
    dotsize: int = 8


@dataclass(frozen=True)
class TimingConfig:
    message_pause_seconds: float = 1.0
    pvp_red_seconds: float = 1.0
    pvp_yellow_min_seconds: float = 0.1
    pvp_yellow_max_seconds: float = 4.0
    pvp_timeout_seconds: float = 10.0
    pvp_second_press_seconds: float = 2.0
    pvp_result_seconds: float = 2.0
    wait_tick_seconds: float = 0.05
    pump_max_seconds: float = 5.0
    boot_seconds: float = 5.0
    boot_scroll_seconds: float = 0.35
    pvp_blink_count: int = 8
    pvp_blink_seconds: float = 0.15
    champion_window_seconds: float = 3600.0


DEFAULT_KEY_BINDINGS: dict[str, Control] = {
    "KEY_KP1": Control.PUMP_1,
    "KEY_KP2": Control.PUMP_2,
    "KEY_KP3": Control.PUMP_3,
    "KEY_KP4": Control.PUMP_4,
    "KEY_KP5": Control.RANDOM_PUMP,
    "KEY_KP6": Control.ALL_PUMPS,
    "KEY_KPPLUS": Control.RAFFLE,
    "KEY_KP7": Control.PLAYER_LEFT,
    "KEY_KP8": Control.PVP_START,
    "KEY_KP9": Control.PLAYER_RIGHT,
    "KEY_KPENTER": Control.STOP_ALL,
}


@dataclass(frozen=True)
class NumpadConfig:
    device_path: str | None = None
    device_name_contains: str | None = None
    grab_input: bool = True
    shutdown_chord: tuple[str, str] = ("KEY_KP0", "KEY_KPASTERISK")
    restart_chord: tuple[str, str] = ("KEY_KP0", "KEY_KPENTER")
    key_bindings: dict[str, Control] = field(
        default_factory=lambda: dict(DEFAULT_KEY_BINDINGS)
    )


@dataclass(frozen=True)
class AppConfig:
    gpio: GpioPins = field(default_factory=GpioPins)
    lcd: LcdConfig = field(default_factory=LcdConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    numpad: NumpadConfig = field(default_factory=NumpadConfig)


def parse_lcd_address(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as exc:
        raise ValueError(
            f"LCD address must be an integer such as 0x27 or 0x3f, got {value!r}"
        ) from exc
