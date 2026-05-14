from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Control(str, Enum):
    PUMP_1 = "pump_1"
    PUMP_2 = "pump_2"
    PUMP_3 = "pump_3"
    PUMP_4 = "pump_4"
    RANDOM_PUMP = "random_pump"
    ALL_PUMPS = "all_pumps"
    PVP_START = "pvp_start"
    PLAYER_LEFT = "player_left"
    PLAYER_RIGHT = "player_right"
    STOP_ALL = "stop_all"


@dataclass(frozen=True)
class OperatorInput:
    control: Control
    pressed: bool

    @property
    def released(self) -> bool:
        return not self.pressed


PUMP_CONTROLS = {
    Control.PUMP_1: 1,
    Control.PUMP_2: 2,
    Control.PUMP_3: 3,
    Control.PUMP_4: 4,
}

