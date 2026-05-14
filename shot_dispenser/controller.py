from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .commands import Control, OperatorInput, PUMP_CONTROLS
from .config import TimingConfig
from .display import Display
from .events import EventPublisher, NullEventPublisher
from .hardware import DispenserHardware
from .messages import DEFAULT_MESSAGES, OperatorMessages


@dataclass
class RunningAction:
    name: str
    stop_event: threading.Event
    thread: threading.Thread | None = None


class ShotDispenserController:
    def __init__(
        self,
        hardware: DispenserHardware,
        display: Display,
        timing: TimingConfig | None = None,
        messages: OperatorMessages = DEFAULT_MESSAGES,
        publisher: EventPublisher | None = None,
        rng: random.Random | None = None,
        pump_count: int = 4,
    ) -> None:
        if pump_count < 1:
            raise ValueError(f"Pump count must be at least 1, got {pump_count}")
        self._hardware = hardware
        self._display = display
        self._timing = timing or TimingConfig()
        self._messages = messages
        self._publisher = publisher or NullEventPublisher()
        self._rng = rng or random.Random()
        self._pump_numbers = tuple(range(1, pump_count + 1))
        self._state_lock = threading.RLock()
        self._active_action: RunningAction | None = None
        self._random_pool: list[int] = []
        self._pvp_active = False
        self._pvp_ready = False
        self._pvp_done = threading.Event()

    def show_ready(self) -> None:
        self._display.show_lines(
            self._messages.title,
            self._messages.ready,
            "",
            self._messages.press_button,
        )

    def handle_input(self, operator_input: OperatorInput) -> None:
        control = operator_input.control

        if control in PUMP_CONTROLS:
            pump_number = PUMP_CONTROLS[control]
            if operator_input.pressed:
                self.start_pump(pump_number)
            else:
                self.stop_pump(pump_number)
            return

        if control is Control.RANDOM_PUMP:
            if operator_input.pressed:
                self.start_random_pump()
            else:
                self.stop_random_pump()
            return

        if control is Control.ALL_PUMPS:
            if operator_input.pressed:
                self.start_all_pumps()
            else:
                self.stop_all_pumps()
            return

        if operator_input.released:
            return

        if control is Control.PVP_START:
            self.start_pvp()
        elif control is Control.PLAYER_LEFT:
            self.player_pressed(1)
        elif control is Control.PLAYER_RIGHT:
            self.player_pressed(2)
        elif control is Control.STOP_ALL:
            self.safe_stop("operator", reset_display=True)

    def start_pump(self, pump_number: int) -> bool:
        if pump_number not in self._pump_numbers:
            raise ValueError(f"Unknown pump {pump_number}")
        return self._start_hold_action(
            f"pump-{pump_number}",
            lambda stop_event: self._run_single_pump(pump_number, stop_event),
        )

    def stop_pump(self, pump_number: int) -> None:
        self._stop_matching_action(f"pump-{pump_number}")

    def start_random_pump(self) -> bool:
        pump_number = self._next_random_pump()
        return self._start_hold_action(
            f"random-pump-{pump_number}",
            lambda stop_event: self._run_single_pump(
                pump_number,
                stop_event,
                random_selection=True,
            ),
        )

    def stop_random_pump(self) -> None:
        self._stop_action_prefix("random-pump-")

    def start_all_pumps(self) -> bool:
        return self._start_hold_action("all-pumps", self._run_all_pumps)

    def stop_all_pumps(self) -> None:
        self._stop_matching_action("all-pumps")

    def start_pvp(self) -> bool:
        action = RunningAction("pvp", self._pvp_done)
        with self._state_lock:
            if self._active_action is not None:
                self._show_busy()
                return False
            self._hardware.traffic_light_off()
            self._pvp_active = True
            self._pvp_ready = False
            self._pvp_done.clear()
            self._active_action = action

        thread = threading.Thread(
            target=self._run_pvp_game,
            args=(action,),
            name="pvp-game",
            daemon=True,
        )
        action.thread = thread
        thread.start()
        return True

    def player_pressed(self, player: int) -> bool:
        if player not in (1, 2):
            raise ValueError(f"Player must be 1 or 2, got {player}")

        with self._state_lock:
            if not self._pvp_active:
                return False
            too_early = not self._pvp_ready
            self._pvp_active = False
            self._pvp_ready = False
            self._pvp_done.set()
            action = self._active_action

        if too_early:
            self._handle_false_start(player, action)
        else:
            self._handle_winner(player, action)
        return True

    def safe_stop(self, reason: str, reset_display: bool = False) -> None:
        with self._state_lock:
            action = self._active_action
            self._active_action = None
            self._pvp_active = False
            self._pvp_ready = False
            self._pvp_done.set()
            if action is not None:
                action.stop_event.set()

        self._hardware.all_off()
        if reset_display:
            self._display.reset()
        self._display.show_lines(
            self._messages.title,
            self._messages.safe_stop,
            reason[: self._display.columns],
            "",
        )
        self._publisher.record_event("safe_stop", {"reason": reason})

    def shutdown(self, reason: str = "shutdown") -> None:
        self.safe_stop(reason)

    def join_idle(self, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._state_lock:
                action = self._active_action
            if action is None:
                return True
            if action.thread is not None:
                remaining = max(0.0, deadline - time.monotonic())
                action.thread.join(min(0.05, remaining))
            else:
                time.sleep(0.01)
        with self._state_lock:
            return self._active_action is None

    def _start_hold_action(
        self,
        name: str,
        target: Callable[[threading.Event], None],
    ) -> bool:
        action = RunningAction(name, threading.Event())

        with self._state_lock:
            if self._active_action is not None or self._pvp_active:
                self._show_busy()
                return False
            self._hardware.traffic_light_off()
            self._active_action = action

        thread = threading.Thread(
            target=self._run_hold_action,
            args=(action, target),
            name=name,
            daemon=True,
        )
        action.thread = thread
        thread.start()
        return True

    def _run_hold_action(
        self,
        action: RunningAction,
        target: Callable[[threading.Event], None],
    ) -> None:
        try:
            target(action.stop_event)
        finally:
            self._hardware.all_pumps_off()
            with self._state_lock:
                if self._active_action is action:
                    self._active_action = None

    def _run_single_pump(
        self,
        pump_number: int,
        stop_event: threading.Event,
        random_selection: bool = False,
    ) -> None:
        event_name = "random_pump_started" if random_selection else "pump_started"
        self._publisher.record_event(event_name, {"pump": pump_number})
        self._hardware.pump_on(pump_number)
        line = (
            self._messages.random_pump.format(pump_number)
            if random_selection
            else self._messages.pump_running.format(pump_number)
        )
        self._display.show_lines(
            self._messages.title,
            line,
            self._messages.release_key,
            "",
        )

        stop_event.wait()
        self._hardware.pump_off(pump_number)
        self._publisher.record_event("pump_stopped", {"pump": pump_number})
        self.show_ready()

    def _run_all_pumps(self, stop_event: threading.Event) -> None:
        self._publisher.record_event("all_pumps_started")
        self._hardware.all_pumps_on()
        self._display.show_lines(
            self._messages.title,
            self._messages.all_pumps,
            self._messages.release_key,
            "",
        )

        stop_event.wait()
        self._hardware.all_pumps_off()
        self._publisher.record_event("all_pumps_stopped")
        self.show_ready()

    def _run_pvp_game(self, action: RunningAction) -> None:
        timed_out = False
        try:
            self._publisher.record_event("pvp_started")
            if self._pvp_done.is_set():
                return
            self._hardware.traffic_light_off()
            self._display.show_lines(self._messages.pvp_title, self._messages.pvp_get_ready)

            if self._pvp_done.is_set():
                return
            self._hardware.red_on()
            self._display.show_lines(
                self._messages.pvp_title,
                self._center(self._messages.pvp_prepare),
                self._center(self._messages.pvp_red),
                "",
            )
            if self._pvp_done.wait(timeout=self._timing.pvp_red_seconds):
                self._hardware.traffic_light_off()
                return

            if self._pvp_done.is_set():
                self._hardware.traffic_light_off()
                return
            self._hardware.red_off()
            self._hardware.yellow_on()
            self._display.show_lines(
                self._messages.pvp_title,
                self._center(self._messages.pvp_almost),
                self._center(self._messages.pvp_yellow),
                "",
            )
            yellow_delay = self._rng.uniform(
                self._timing.pvp_yellow_min_seconds,
                self._timing.pvp_yellow_max_seconds,
            )
            if self._pvp_done.wait(timeout=yellow_delay):
                self._hardware.traffic_light_off()
                return

            if self._pvp_done.is_set():
                self._hardware.traffic_light_off()
                return
            self._hardware.yellow_off()
            self._hardware.green_on()
            with self._state_lock:
                if not self._pvp_active:
                    return
                self._pvp_ready = True
            self._display.show_lines(
                self._messages.pvp_title,
                "",
                self._center(self._messages.pvp_now),
                "",
            )

            self._pvp_done.wait(timeout=self._timing.pvp_timeout_seconds)
            with self._state_lock:
                timed_out = self._pvp_active
                if timed_out:
                    self._pvp_active = False
                    self._pvp_ready = False

            if timed_out:
                self._hardware.traffic_light_off()
                self._display.show_lines(
                    self._messages.pvp_title,
                    self._center(self._messages.pvp_too_slow),
                    self._center(self._messages.pvp_nobody_wins),
                    "",
                )
                self._publisher.record_event("pvp_timeout")
                self._pause(self._timing.pvp_result_seconds)
                self.show_ready()
        finally:
            if timed_out or action.stop_event.is_set():
                self._clear_active(action)

    def _handle_false_start(
        self,
        player: int,
        action: RunningAction | None,
    ) -> None:
        self._hardware.traffic_light_off()
        self._display.show_lines(
            self._messages.pvp_title,
            self._center(self._messages.pvp_player.format(player)),
            self._center(self._messages.pvp_too_early),
            "",
        )
        self._publisher.record_event("pvp_false_start", {"player": player})
        self._hardware.blink_yellow(count=5, seconds=0.1)
        self._pause(self._timing.message_pause_seconds)
        self.show_ready()
        self._clear_active(action)

    def _handle_winner(self, player: int, action: RunningAction | None) -> None:
        self._hardware.green_off()
        if player == 1:
            self._hardware.red_on()
            winner = self._messages.pvp_left_wins
        else:
            self._hardware.green_on()
            winner = self._messages.pvp_right_wins

        self._display.show_lines(
            self._messages.pvp_title,
            self._center(winner),
            self._center(self._messages.pvp_wins),
            self._messages.pvp_restart,
        )
        self._publisher.record_event("pvp_winner", {"player": player})
        self._clear_active(action)

    def _next_random_pump(self) -> int:
        with self._state_lock:
            if not self._random_pool:
                self._random_pool = list(self._pump_numbers)
                self._rng.shuffle(self._random_pool)
            return self._random_pool.pop()

    def _stop_matching_action(self, name: str) -> None:
        with self._state_lock:
            action = self._active_action
            if action is not None and action.name == name:
                action.stop_event.set()

    def _stop_action_prefix(self, prefix: str) -> None:
        with self._state_lock:
            action = self._active_action
            if action is not None and action.name.startswith(prefix):
                action.stop_event.set()

    def _clear_active(self, action: RunningAction | None) -> None:
        if action is None:
            return
        with self._state_lock:
            if self._active_action is action:
                self._active_action = None

    def _show_busy(self) -> None:
        self._display.show_lines(self._messages.title, self._messages.busy, "", "")

    def _center(self, text: str) -> str:
        return text.center(self._display.columns)

    def _pause(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)
