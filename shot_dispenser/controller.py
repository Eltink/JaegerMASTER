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

_CHAMPION_WINDOW_SECONDS = 3600.0  # 1 hour


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

        # Multiple pump actions can run concurrently; PvP is exclusive.
        self._pump_actions: dict[str, RunningAction] = {}

        # PvP state
        self._pvp_active = False
        self._pvp_in_setup = False       # True while waiting for both players to ready up
        self._pvp_ready = False          # True from green light until a player presses
        self._pvp_done = threading.Event()
        self._pvp_ready_players: set[int] = set()
        self._pvp_green_time: float = 0.0
        self._pvp_reaction_times: dict[int, float] = {}

        # Champion tracking (in-memory, resets on restart)
        self._pvp_champion_ms: float | None = None
        self._pvp_champion_set_time: float = 0.0

        self._random_pool: list[int] = []

    def show_ready(self) -> None:
        champion_line = self._messages.main_line4
        if self._pvp_champion_ms is not None:
            if time.monotonic() - self._pvp_champion_set_time <= _CHAMPION_WINDOW_SECONDS:
                champion_line = self._messages.pvp_champion.format(
                    int(self._pvp_champion_ms)
                )
        self._display.show_lines(
            self._messages.main_line1,
            self._messages.main_line2,
            self._messages.main_line3,
            champion_line,
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

        if control is Control.LOTTERY:
            if operator_input.pressed:
                self.start_lottery()
            else:
                self.stop_lottery()
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

    # ─── Pump actions ──────────────────────────────────────────────────────

    def start_pump(self, pump_number: int) -> bool:
        if pump_number not in self._pump_numbers:
            raise ValueError(f"Unknown pump {pump_number}")
        return self._start_pump_action(
            f"pump-{pump_number}",
            lambda stop_event: self._run_single_pump(pump_number, stop_event),
        )

    def stop_pump(self, pump_number: int) -> None:
        self._stop_pump_action(f"pump-{pump_number}")

    def start_random_pump(self) -> bool:
        pump_number = self._next_random_pump()
        return self._start_pump_action(
            f"random-pump-{pump_number}",
            lambda stop_event: self._run_single_pump(
                pump_number, stop_event, random_selection=True
            ),
        )

    def stop_random_pump(self) -> None:
        with self._state_lock:
            for name in list(self._pump_actions):
                if name.startswith("random-pump-"):
                    self._pump_actions[name].stop_event.set()

    def start_all_pumps(self) -> bool:
        return self._start_pump_action("all-pumps", self._run_all_pumps)

    def stop_all_pumps(self) -> None:
        self._stop_pump_action("all-pumps")

    def start_lottery(self) -> bool:
        return self._start_pump_action("lottery", self._run_lottery)

    def stop_lottery(self) -> None:
        self._stop_pump_action("lottery")

    # ─── PvP ───────────────────────────────────────────────────────────────

    def start_pvp(self) -> bool:
        with self._state_lock:
            if self._pump_actions or self._pvp_active:
                self._show_busy()
                return False
            self._hardware.traffic_light_off()
            self._pvp_active = True
            self._pvp_in_setup = True
            self._pvp_ready = False
            self._pvp_done.clear()
            self._pvp_ready_players = set()
            self._pvp_reaction_times = {}

        self._display.show_lines(
            self._messages.pvp_title,
            self._messages.pvp_left_button,
            self._messages.pvp_right_button,
            self._messages.pvp_press_button,
        )
        return True

    def player_pressed(self, player: int) -> bool:
        if player not in (1, 2):
            raise ValueError(f"Player must be 1 or 2, got {player}")

        with self._state_lock:
            if not self._pvp_active:
                return False

            if self._pvp_in_setup:
                # ── Setup phase: collect ready confirmations from both players ──
                self._pvp_ready_players.add(player)
                both_ready = len(self._pvp_ready_players) == 2
                if both_ready:
                    self._pvp_in_setup = False
                self._show_setup_state(player, both_ready)
                if both_ready:
                    self._launch_pvp_countdown()
                return True

        # ── Game phase (outside lock): first press wins (or false start) ──
        with self._state_lock:
            if not self._pvp_active:
                return False
            too_early = not self._pvp_ready
            self._pvp_active = False
            self._pvp_ready = False
            self._pvp_done.set()

        if too_early:
            self._handle_false_start(player)
        else:
            reaction_ms = (time.monotonic() - self._pvp_green_time) * 1000.0
            self._pvp_reaction_times[player] = reaction_ms
            self._update_champion(reaction_ms)
            self._handle_winner(player)
        return True

    def _show_setup_state(self, just_pressed: int, both_ready: bool) -> None:
        """Update display during setup phase (called under state lock)."""
        if both_ready:
            self._display.show_lines(
                self._messages.pvp_title,
                self._center(self._messages.pvp_get_ready),
                "",
                "",
            )
            return
        p1 = self._messages.pvp_p1_ready if 1 in self._pvp_ready_players else self._messages.pvp_left_button
        p2 = self._messages.pvp_p2_ready if 2 in self._pvp_ready_players else self._messages.pvp_right_button
        wait = self._messages.pvp_waiting_p2 if just_pressed == 1 else self._messages.pvp_waiting_p1
        self._display.show_lines(self._messages.pvp_title, p1, p2, wait)

    def _launch_pvp_countdown(self) -> None:
        """Start the countdown thread after both players have confirmed ready."""
        self._pvp_done.clear()
        thread = threading.Thread(
            target=self._run_pvp_game,
            name="pvp-game",
            daemon=True,
        )
        thread.start()

    # ─── Safe stop / shutdown ──────────────────────────────────────────────

    def safe_stop(self, reason: str, reset_display: bool = False) -> None:
        with self._state_lock:
            actions = list(self._pump_actions.values())
            self._pump_actions.clear()
            self._pvp_active = False
            self._pvp_in_setup = False
            self._pvp_ready = False
            self._pvp_done.set()
            for action in actions:
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
                threads = [
                    a.thread for a in self._pump_actions.values() if a.thread is not None
                ]
                pvp_running = self._pvp_active
            if not threads and not pvp_running:
                return True
            for t in threads:
                remaining = max(0.0, deadline - time.monotonic())
                t.join(min(0.05, remaining))
            if pvp_running:
                time.sleep(0.01)
        with self._state_lock:
            return not self._pump_actions and not self._pvp_active

    # ─── Pump action internals ─────────────────────────────────────────────

    def _start_pump_action(
        self,
        name: str,
        target: Callable[[threading.Event], None],
    ) -> bool:
        with self._state_lock:
            if self._pvp_active:
                self._show_busy()
                return False
            if name in self._pump_actions:
                return False  # already running; silently ignore
            action = RunningAction(name, threading.Event())
            self._pump_actions[name] = action
            self._hardware.traffic_light_off()

        thread = threading.Thread(
            target=self._run_pump_action,
            args=(name, action, target),
            name=name,
            daemon=True,
        )
        action.thread = thread
        thread.start()
        return True

    def _run_pump_action(
        self,
        name: str,
        action: RunningAction,
        target: Callable[[threading.Event], None],
    ) -> None:
        try:
            target(action.stop_event)
        finally:
            with self._state_lock:
                self._pump_actions.pop(name, None)
                idle = not self._pump_actions and not self._pvp_active
            if idle:
                self.show_ready()
            else:
                self._update_pump_display()

    def _run_single_pump(
        self,
        pump_number: int,
        stop_event: threading.Event,
        random_selection: bool = False,
    ) -> None:
        event_name = "random_pump_started" if random_selection else "pump_started"
        self._publisher.record_event(event_name, {"pump": pump_number})
        self._hardware.pump_on(pump_number)
        self._update_pump_display()
        stop_event.wait(timeout=self._timing.pump_max_seconds)
        self._hardware.pump_off(pump_number)
        self._publisher.record_event("pump_stopped", {"pump": pump_number})

    def _run_all_pumps(self, stop_event: threading.Event) -> None:
        self._publisher.record_event("all_pumps_started")
        self._hardware.all_pumps_on()
        self._display.show_lines(
            self._messages.title,
            self._messages.all_pumps,
            self._messages.release_key,
            "",
        )
        stop_event.wait(timeout=self._timing.pump_max_seconds)
        self._hardware.all_pumps_off()
        self._publisher.record_event("all_pumps_stopped")

    def _run_lottery(self, stop_event: threading.Event) -> None:
        r = self._rng.random()
        if r < 0.10:
            count = 1
        elif r < 0.20:
            count = 2
        elif r < 0.40:
            count = 3
        else:
            count = 4

        pool = list(self._pump_numbers)
        self._rng.shuffle(pool)
        selected = pool[:count]

        self._publisher.record_event("lottery_started", {"pumps": selected, "count": count})
        for p in selected:
            self._hardware.pump_on(p)
        self._display.show_lines(
            self._messages.title,
            self._messages.lottery_msg.format(count),
            self._messages.release_key,
            "",
        )
        stop_event.wait(timeout=self._timing.pump_max_seconds)
        for p in selected:
            self._hardware.pump_off(p)
        self._publisher.record_event("lottery_stopped", {"pumps": selected})

    def _update_pump_display(self) -> None:
        with self._state_lock:
            names = list(self._pump_actions.keys())

        if not names:
            return

        # Build a list of pump numbers from active actions
        pump_nums: list[int] = []
        for name in names:
            if name.startswith("pump-"):
                try:
                    pump_nums.append(int(name.split("-")[1]))
                except (IndexError, ValueError):
                    pass
            elif name.startswith("random-pump-"):
                try:
                    pump_nums.append(int(name.split("-")[2]))
                except (IndexError, ValueError):
                    pass
        pump_nums.sort()

        if len(names) == 1 and not pump_nums:
            # lottery or all-pumps already set their own display
            return

        if len(pump_nums) == 1:
            line = self._messages.pump_running.format(pump_nums[0])
            line2 = self._messages.release_key
        else:
            nums_str = ",".join(str(n) for n in pump_nums)
            line = self._messages.pump_multi.format(nums_str)
            line2 = self._messages.release_key

        self._display.show_lines(self._messages.title, line, line2, "")

    def _stop_pump_action(self, name: str) -> None:
        with self._state_lock:
            action = self._pump_actions.get(name)
            if action is not None:
                action.stop_event.set()

    # ─── PvP internals ────────────────────────────────────────────────────

    def _run_pvp_game(self) -> None:
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
                self._pvp_green_time = time.monotonic()
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
            if timed_out:
                with self._state_lock:
                    self._pvp_active = False

    def _handle_false_start(self, player: int) -> None:
        self._hardware.traffic_light_off()
        self._display.show_lines(
            self._messages.pvp_title,
            self._center(self._messages.pvp_player.format(player)),
            self._center(self._messages.pvp_too_early),
            "",
        )
        self._publisher.record_event("pvp_false_start", {"player": player})
        self._hardware.blink_yellow(count=5, seconds=0.1)
        # Clear pvp state before show_ready to avoid "Aguarde..." race
        with self._state_lock:
            self._pvp_active = False
        self._pause(self._timing.message_pause_seconds)
        self.show_ready()

    def _handle_winner(self, player: int) -> None:
        self._hardware.traffic_light_off()

        reaction_ms = self._pvp_reaction_times.get(player, 0.0)
        other_player = 3 - player  # 1→2, 2→1
        other_ms = self._pvp_reaction_times.get(other_player, 0.0)

        # Left player (1) = green LED; right player (2) = red LED
        if player == 1:
            winner_msg = self._messages.pvp_left_wins
        else:
            winner_msg = self._messages.pvp_right_wins

        e_ms = reaction_ms if player == 1 else other_ms
        d_ms = reaction_ms if player == 2 else other_ms
        time_line = f"Esq:{int(e_ms)}ms Dir:{int(d_ms)}ms"

        self._display.show_lines(
            self._messages.pvp_title,
            time_line[: self._display.columns],
            self._center(winner_msg + " " + self._messages.pvp_wins),
            self._messages.pvp_restart,
        )
        self._publisher.record_event("pvp_winner", {"player": player, "ms": reaction_ms})

        # Blink the winner's LED (left=green, right=red)
        if player == 1:
            self._hardware.blink_green(
                count=self._timing.pvp_blink_count,
                seconds=self._timing.pvp_blink_seconds,
            )
        else:
            self._hardware.blink_red(
                count=self._timing.pvp_blink_count,
                seconds=self._timing.pvp_blink_seconds,
            )

    def _update_champion(self, reaction_ms: float) -> None:
        now = time.monotonic()
        if (
            self._pvp_champion_ms is not None
            and now - self._pvp_champion_set_time > _CHAMPION_WINDOW_SECONDS
        ):
            self._pvp_champion_ms = None

        if self._pvp_champion_ms is None or reaction_ms < self._pvp_champion_ms:
            self._pvp_champion_ms = reaction_ms
            self._pvp_champion_set_time = now

    # ─── Shared helpers ───────────────────────────────────────────────────

    def _next_random_pump(self) -> int:
        with self._state_lock:
            if not self._random_pool:
                self._random_pool = list(self._pump_numbers)
                self._rng.shuffle(self._random_pool)
            return self._random_pool.pop()

    def _show_busy(self) -> None:
        self._display.show_lines(self._messages.title, self._messages.busy, "", "")

    def _center(self, text: str) -> str:
        return text.center(self._display.columns)

    def _pause(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)
