from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .commands import Control, OperatorInput, PUMP_CONTROLS
from .config import TimingConfig
from .display import Display
from .events import EventPublisher, NullEventPublisher
from .hardware import DispenserHardware
from .messages import DEFAULT_MESSAGES, OperatorMessages


PVP_TEST = "test"
PVP_COUNTDOWN = "countdown"
PVP_ARMED = "armed"
PVP_DONE = "done"


@dataclass
class RunningAction:
    name: str
    stop_event: threading.Event
    thread: threading.Thread | None = None


@dataclass
class PvpState:
    phase: str = PVP_TEST
    left_tested: bool = False
    right_tested: bool = False
    green_at: float | None = None
    reactions: dict[int, int] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    false_start: int | None = None
    changed: threading.Event = field(default_factory=threading.Event)


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
        self._pump_actions: dict[int, RunningAction] = {}
        self._exclusive: RunningAction | None = None
        self._random_pool: list[int] = []
        self._pvp: PvpState | None = None
        self._champion_times: list[tuple[float, int]] = []
        self._screen_locked = False

    # ----- screens -------------------------------------------------------

    def _title(self) -> str:
        return self._messages.title.center(self._display.columns)

    def show_ready(self) -> None:
        if self._screen_locked:
            return
        self._display.show_lines(*self._messages.main_art)

    def is_idle(self) -> bool:
        with self._state_lock:
            return not self._pump_actions and self._exclusive is None

    # ----- input routing -------------------------------------------------

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

        if control is Control.RAFFLE:
            if operator_input.pressed:
                self.start_raffle()
            else:
                self.stop_raffle()
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

    # ----- single / multi pump ------------------------------------------

    def start_pump(self, pump_number: int) -> bool:
        if pump_number not in self._pump_numbers:
            raise ValueError(f"Unknown pump {pump_number}")
        action = RunningAction(f"pump-{pump_number}", threading.Event())
        with self._state_lock:
            if self._exclusive is not None or self._pvp is not None:
                self._show_busy()
                return False
            if pump_number in self._pump_actions:
                return False
            self._hardware.traffic_light_off()
            self._pump_actions[pump_number] = action
        thread = threading.Thread(
            target=self._run_pump,
            args=(pump_number, action),
            name=action.name,
            daemon=True,
        )
        action.thread = thread
        thread.start()
        return True

    def stop_pump(self, pump_number: int) -> None:
        with self._state_lock:
            action = self._pump_actions.get(pump_number)
            if action is not None:
                action.stop_event.set()

    def _run_pump(self, pump_number: int, action: RunningAction) -> None:
        limited = False
        try:
            self._publisher.record_event("pump_started", {"pump": pump_number})
            self._hardware.pump_on(pump_number)
            self._render_pumps()
            timed_out = not action.stop_event.wait(
                timeout=self._timing.pump_max_seconds
            )
            limited = timed_out
        finally:
            self._hardware.pump_off(pump_number)
            with self._state_lock:
                if self._pump_actions.get(pump_number) is action:
                    del self._pump_actions[pump_number]
                still_running = bool(self._pump_actions)
            self._publisher.record_event("pump_stopped", {"pump": pump_number})
            if limited:
                self._publisher.record_event("pump_limit", {"pump": pump_number})
            if still_running:
                self._render_pumps()
            elif limited:
                self._display.show_lines(
                    self._title(),
                    self._messages.pump_limit,
                    "",
                    "",
                )
                self._pause(self._timing.message_pause_seconds)
                if self.is_idle():
                    self.show_ready()
            else:
                self.show_ready()

    def _render_pumps(self) -> None:
        with self._state_lock:
            active = sorted(self._pump_actions)
        if not active:
            return
        numbers = " ".join(str(n) for n in active)
        self._display.show_lines(
            self._title(),
            self._messages.pumps_running.format(numbers),
            self._messages.release_key,
            "",
        )

    # ----- exclusive actions: random / all / raffle ----------------------

    def start_random_pump(self) -> bool:
        pump_number = self._next_random_pump()
        return self._start_exclusive(
            f"random-pump-{pump_number}",
            lambda stop_event: self._run_single_pump(pump_number, stop_event),
        )

    def stop_random_pump(self) -> None:
        self._stop_exclusive_prefix("random-pump-")

    def start_all_pumps(self) -> bool:
        return self._start_exclusive("all-pumps", self._run_all_pumps)

    def stop_all_pumps(self) -> None:
        self._stop_exclusive_name("all-pumps")

    def start_raffle(self) -> bool:
        pumps = self._raffle_pumps()
        return self._start_exclusive(
            "raffle",
            lambda stop_event: self._run_raffle(pumps, stop_event),
        )

    def stop_raffle(self) -> None:
        self._stop_exclusive_name("raffle")

    def _raffle_pumps(self) -> list[int]:
        roll = self._rng.random()
        if roll < 0.60:
            count = len(self._pump_numbers)
        elif roll < 0.80:
            count = 3
        elif roll < 0.90:
            count = 2
        else:
            count = 1
        count = min(count, len(self._pump_numbers))
        return sorted(self._rng.sample(self._pump_numbers, count))

    def _start_exclusive(
        self,
        name: str,
        target: Callable[[threading.Event], None],
    ) -> bool:
        action = RunningAction(name, threading.Event())
        with self._state_lock:
            if (
                self._exclusive is not None
                or self._pump_actions
                or self._pvp is not None
            ):
                self._show_busy()
                return False
            self._hardware.traffic_light_off()
            self._exclusive = action
        thread = threading.Thread(
            target=self._run_exclusive,
            args=(action, target),
            name=name,
            daemon=True,
        )
        action.thread = thread
        thread.start()
        return True

    def _run_exclusive(
        self,
        action: RunningAction,
        target: Callable[[threading.Event], None],
    ) -> None:
        try:
            target(action.stop_event)
        finally:
            self._hardware.all_pumps_off()
            with self._state_lock:
                if self._exclusive is action:
                    self._exclusive = None

    def _wait_with_limit(self, stop_event: threading.Event) -> bool:
        """Wait for release or the 5s safety cut. Returns True if limited."""
        return not stop_event.wait(timeout=self._timing.pump_max_seconds)

    def _run_single_pump(
        self,
        pump_number: int,
        stop_event: threading.Event,
    ) -> None:
        self._publisher.record_event("random_pump_started", {"pump": pump_number})
        self._hardware.pump_on(pump_number)
        self._display.show_lines(
            self._title(),
            self._center(self._messages.random_pump.format(pump_number)),
            self._center(f">> Bomba {pump_number} <<"),
            self._center(self._messages.release_key),
        )
        limited = self._wait_with_limit(stop_event)
        self._hardware.pump_off(pump_number)
        self._publisher.record_event("pump_stopped", {"pump": pump_number})
        self._finish_exclusive(limited)

    def _run_all_pumps(self, stop_event: threading.Event) -> None:
        self._publisher.record_event("all_pumps_started")
        self._hardware.all_pumps_on()
        self._display.show_lines(
            self._title(),
            self._messages.all_pumps,
            self._messages.release_key,
            "",
        )
        limited = self._wait_with_limit(stop_event)
        self._hardware.all_pumps_off()
        self._publisher.record_event("all_pumps_stopped")
        self._finish_exclusive(limited)

    def _run_raffle(self, pumps: list[int], stop_event: threading.Event) -> None:
        numbers = " ".join(str(n) for n in pumps)
        self._publisher.record_event("raffle_started", {"pumps": list(pumps)})
        for pump_number in pumps:
            self._hardware.pump_on(pump_number)
        self._display.show_lines(
            self._title(),
            self._messages.raffle_running.format(numbers),
            self._messages.release_key,
            "",
        )
        limited = self._wait_with_limit(stop_event)
        for pump_number in pumps:
            self._hardware.pump_off(pump_number)
        self._publisher.record_event("raffle_stopped")
        self._finish_exclusive(limited)

    def _finish_exclusive(self, limited: bool) -> None:
        if limited:
            self._publisher.record_event("pump_limit")
            self._display.show_lines(
                self._title(),
                self._messages.pump_limit,
                "",
                "",
            )
            self._pause(self._timing.message_pause_seconds)
        self.show_ready()

    # ----- PvP -----------------------------------------------------------

    def start_pvp(self) -> bool:
        action = RunningAction("pvp", threading.Event())
        with self._state_lock:
            current = self._pvp
            if current is not None and current.phase == PVP_DONE:
                # The result is on screen: KP8 acknowledges it, leaves PvP
                # and re-enables pouring instead of starting a new round.
                self._pvp = None
                exit_pvp = True
            elif current is not None:
                # A round is already running; ignore extra KP8 presses.
                return False
            else:
                exit_pvp = False
                if self._pump_actions or self._exclusive is not None:
                    self._show_busy()
                    return False
        if exit_pvp:
            self._hardware.traffic_light_off()
            self.show_ready()
            return True
        with self._state_lock:
            if self._pump_actions or self._exclusive is not None:
                self._show_busy()
                return False
            self._hardware.traffic_light_off()
            pvp = PvpState()
            self._pvp = pvp
            self._exclusive = action
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
        now = time.monotonic()
        with self._state_lock:
            pvp = self._pvp
            if pvp is None:
                return False
            phase = pvp.phase
            if phase == PVP_TEST:
                if player == 1:
                    pvp.left_tested = True
                else:
                    pvp.right_tested = True
            elif phase == PVP_COUNTDOWN:
                if pvp.false_start is None:
                    pvp.false_start = player
            elif phase == PVP_ARMED:
                if player not in pvp.reactions and pvp.green_at is not None:
                    pvp.reactions[player] = int((now - pvp.green_at) * 1000)
                    pvp.order.append(player)
            else:
                return False
            pvp.changed.set()
        return True

    def _pvp_aborted(self, action: RunningAction) -> bool:
        if action.stop_event.is_set():
            return True
        with self._state_lock:
            return self._pvp is None

    def _run_pvp_game(self, action: RunningAction) -> None:
        try:
            self._publisher.record_event("pvp_started")
            if not self._pvp_test_phase(action):
                return
            if not self._pvp_countdown(action):
                return
            self._pvp_round(action)
        finally:
            with self._state_lock:
                if self._exclusive is action:
                    self._exclusive = None
                    if action.stop_event.is_set():
                        self._pvp = None
            self._hardware.all_pumps_off()

    def _pvp_test_phase(self, action: RunningAction) -> bool:
        with self._state_lock:
            pvp = self._pvp
        if pvp is None or self._pvp_aborted(action):
            return False
        last_left: bool | None = None
        last_right: bool | None = None
        while True:
            with self._state_lock:
                pvp = self._pvp
                if pvp is None or action.stop_event.is_set():
                    return False
                left = pvp.left_tested
                right = pvp.right_tested
            if left != last_left or right != last_right:
                last_left = left
                last_right = right
                self._hardware.green_off()
                self._hardware.red_off()
                if left:
                    self._hardware.green_on()
                if right:
                    self._hardware.red_on()
                self._display.show_lines(
                    self._messages.pvp_test_title,
                    self._messages.pvp_test_left
                    + (
                        " " + self._messages.pvp_test_ok
                        if left
                        else ""
                    ),
                    self._messages.pvp_test_right
                    + (
                        " " + self._messages.pvp_test_ok
                        if right
                        else ""
                    ),
                    "",
                )
            if left and right:
                self._hardware.traffic_light_off()
                return True
            pvp.changed.wait(timeout=self._timing.wait_tick_seconds)
            pvp.changed.clear()

    def _pvp_countdown(self, action: RunningAction) -> bool:
        with self._state_lock:
            pvp = self._pvp
        if pvp is None or action.stop_event.is_set():
            return False
        with self._state_lock:
            self._pvp.phase = PVP_COUNTDOWN

        self._hardware.red_on()
        self._display.show_lines(
            self._messages.pvp_title,
            self._center(self._messages.pvp_prepare),
            self._center(self._messages.pvp_red),
            "",
        )
        if not self._pvp_stage(action, self._timing.pvp_red_seconds):
            return False

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
        if not self._pvp_stage(action, yellow_delay):
            return False

        self._hardware.yellow_off()
        with self._state_lock:
            pvp = self._pvp
            aborted = pvp is None or action.stop_event.is_set()
            false_player = None if pvp is None else pvp.false_start
            if not aborted and false_player is None:
                self._hardware.green_on()
                pvp.green_at = time.monotonic()
                pvp.phase = PVP_ARMED
                pvp.changed.clear()
        if aborted:
            self._hardware.traffic_light_off()
            return False
        if false_player is not None:
            self._handle_false_start(action, false_player)
            return False
        self._display.show_lines(
            self._messages.pvp_title,
            "",
            self._center(self._messages.pvp_now),
            "",
        )
        return True

    def _pvp_stage(self, action: RunningAction, seconds: float) -> bool:
        """Run one countdown stage.

        Returns True to continue the countdown, False to stop it (the stage
        was aborted, or handled a false start itself).
        """
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            with self._state_lock:
                pvp = self._pvp
                aborted = pvp is None or action.stop_event.is_set()
                false_player = None if pvp is None else pvp.false_start
            if aborted:
                self._hardware.traffic_light_off()
                return False
            if false_player is not None:
                self._handle_false_start(action, false_player)
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            pvp.changed.wait(timeout=min(remaining, self._timing.wait_tick_seconds))
            pvp.changed.clear()

    def _pvp_round(self, action: RunningAction) -> None:
        deadline = time.monotonic() + self._timing.pvp_timeout_seconds
        first_press_at: float | None = None
        while True:
            with self._state_lock:
                pvp = self._pvp
                aborted = pvp is None or action.stop_event.is_set()
                false_player = None if pvp is None else pvp.false_start
                pressed = 0 if pvp is None else len(pvp.reactions)
            if aborted:
                self._hardware.traffic_light_off()
                return
            if false_player is not None:
                self._handle_false_start(action, false_player)
                return
            now = time.monotonic()
            if pressed >= 1 and first_press_at is None:
                first_press_at = now
            # Both reacted, the loser ran out of their grace window after the
            # first press, or nobody pressed before the overall timeout.
            grace_over = (
                first_press_at is not None
                and now - first_press_at >= self._timing.pvp_second_press_seconds
            )
            if pressed >= 2 or grace_over or now >= deadline:
                self._finish_pvp(action)
                return
            pvp.changed.wait(timeout=self._timing.wait_tick_seconds)
            pvp.changed.clear()

    def _finish_pvp(self, action: RunningAction) -> None:
        with self._state_lock:
            pvp = self._pvp
            if pvp is None:
                return
            order = list(pvp.order)
            reactions = dict(pvp.reactions)
            pvp.phase = PVP_DONE

        now = time.monotonic()
        for ms in reactions.values():
            self._champion_times.append((now, ms))
        self._prune_champions(now)

        left_ms = reactions.get(1)
        right_ms = reactions.get(2)

        if not order:
            self._hardware.traffic_light_off()
            self._display.show_lines(
                self._messages.pvp_title,
                self._center(self._messages.pvp_too_slow),
                self._center(self._messages.pvp_nobody_wins),
                self._center(self._champion_line()),
            )
            self._publisher.record_event("pvp_timeout")
            self._pause(self._timing.pvp_result_seconds)
            self.show_ready()
            return

        winner = order[0]
        self._hardware.traffic_light_off()
        winner_text = (
            self._messages.pvp_left_wins
            if winner == 1
            else self._messages.pvp_right_wins
        )
        self._display.show_lines(
            self._center(f"{winner_text} {self._messages.pvp_wins}"),
            self._center(self._reaction_line(left_ms, right_ms)),
            self._center(self._champion_line()),
            self._center(self._messages.pvp_restart),
        )
        self._publisher.record_event(
            "pvp_winner",
            {"player": winner, "reactions": reactions},
        )
        blink_color = "green" if winner == 1 else "red"
        self._hardware.blink_led(
            blink_color,
            self._timing.pvp_blink_count,
            self._timing.pvp_blink_seconds,
        )
        if winner == 1:
            self._hardware.green_on()
        else:
            self._hardware.red_on()

    def _handle_false_start(self, action: RunningAction, player: int) -> None:
        with self._state_lock:
            pvp = self._pvp
            if pvp is not None:
                pvp.phase = PVP_DONE
        self._hardware.traffic_light_off()
        self._display.show_lines(
            self._messages.pvp_title,
            self._center(self._messages.pvp_player.format(player)),
            self._center(self._messages.pvp_too_early),
            self._center(self._messages.pvp_restart),
        )
        self._publisher.record_event("pvp_false_start", {"player": player})
        self._hardware.blink_yellow(count=5, seconds=0.1)

    def _reaction_line(self, left_ms: int | None, right_ms: int | None) -> str:
        left = (
            str(left_ms)
            if left_ms is not None
            else self._messages.pvp_no_reaction
        )
        right = (
            str(right_ms)
            if right_ms is not None
            else self._messages.pvp_no_reaction
        )
        return f"E:{left} D:{right} ms"[: self._display.columns]

    def _champion_line(self) -> str:
        best = self.champion_ms()
        if best is None:
            return ""
        return self._messages.pvp_champion.format(best)

    def champion_ms(self) -> int | None:
        now = time.monotonic()
        self._prune_champions(now)
        with self._state_lock:
            if not self._champion_times:
                return None
            return min(ms for _, ms in self._champion_times)

    def _prune_champions(self, now: float) -> None:
        window = self._timing.champion_window_seconds
        with self._state_lock:
            self._champion_times = [
                (ts, ms)
                for ts, ms in self._champion_times
                if now - ts <= window
            ]

    # ----- stop / power --------------------------------------------------

    def safe_stop(self, reason: str, reset_display: bool = False) -> None:
        self._stop_everything()
        self._hardware.all_off()
        if reset_display:
            self._display.reset()
        self._display.show_lines(
            self._title(),
            self._messages.safe_stop,
            reason[: self._display.columns],
            "",
        )
        self._publisher.record_event("safe_stop", {"reason": reason})

    def shutdown(self, reason: str = "shutdown") -> None:
        self._screen_locked = True
        self._stop_everything()
        self._hardware.all_off()
        self._display.show_lines(
            self._title(),
            self._messages.shutting_down,
            reason[: self._display.columns],
            "",
        )
        self._publisher.record_event("shutdown", {"reason": reason})
        self._pause(self._timing.message_pause_seconds)
        self._display.set_backlight(False)

    def restart(self, reason: str = "restart") -> None:
        self._screen_locked = True
        self._stop_everything()
        self._hardware.all_off()
        self._display.show_lines(
            self._title(),
            self._messages.restarting,
            reason[: self._display.columns],
            "",
        )
        self._publisher.record_event("restart", {"reason": reason})

    def _stop_everything(self) -> None:
        with self._state_lock:
            actions = list(self._pump_actions.values())
            if self._exclusive is not None:
                actions.append(self._exclusive)
            self._pump_actions = {}
            self._exclusive = None
            self._pvp = None
            for action in actions:
                action.stop_event.set()

    def join_idle(self, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._state_lock:
                threads = [
                    a.thread
                    for a in list(self._pump_actions.values())
                    if a.thread is not None
                ]
                if self._exclusive is not None and self._exclusive.thread is not None:
                    threads.append(self._exclusive.thread)
                idle = not self._pump_actions and self._exclusive is None
            if idle:
                return True
            remaining = max(0.0, deadline - time.monotonic())
            if threads:
                threads[0].join(min(0.05, remaining))
            else:
                time.sleep(0.01)
        return self.is_idle()

    # ----- boot ----------------------------------------------------------

    def play_boot_sequence(self, stop_event: threading.Event | None = None) -> None:
        stop_event = stop_event or threading.Event()
        # A single static screen for the whole boot window. The numpad runs
        # on another thread, so an operator action can still repaint over
        # this; the boot screen itself never repaints, so it cannot flicker.
        self._display.show_lines(
            self._title(),
            self._center(self._messages.booting),
            self._messages.boot_credit_1,
            self._messages.boot_credit_2,
        )
        stop_event.wait(timeout=self._timing.boot_seconds)
        if not stop_event.is_set() and self.is_idle():
            self.show_ready()

    # ----- helpers -------------------------------------------------------

    def _next_random_pump(self) -> int:
        with self._state_lock:
            if not self._random_pool:
                self._random_pool = list(self._pump_numbers)
                self._rng.shuffle(self._random_pool)
            return self._random_pool.pop()

    def _stop_exclusive_name(self, name: str) -> None:
        with self._state_lock:
            action = self._exclusive
            if action is not None and action.name == name:
                action.stop_event.set()

    def _stop_exclusive_prefix(self, prefix: str) -> None:
        with self._state_lock:
            action = self._exclusive
            if action is not None and action.name.startswith(prefix):
                action.stop_event.set()

    def _show_busy(self) -> None:
        self._display.show_lines(self._title(), self._messages.busy, "", "")

    def _center(self, text: str) -> str:
        return text.center(self._display.columns)

    def _pause(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)
