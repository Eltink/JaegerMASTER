from __future__ import annotations

import random
import threading
import time
import unittest

from shot_dispenser.commands import Control, OperatorInput
from shot_dispenser.config import TimingConfig
from shot_dispenser.controller import (
    PVP_DONE,
    PvpState,
    RunningAction,
    ShotDispenserController,
)
from shot_dispenser.display import Display
from shot_dispenser.events import RecordingEventPublisher
from shot_dispenser.hardware import FakeHardware


class MemoryDisplay:
    columns = 20
    rows = 4

    def __init__(self) -> None:
        self.history: list[tuple[str, ...]] = []
        self.reset_count = 0

    def show_lines(self, *lines: str) -> None:
        self.history.append(tuple(lines))

    def clear(self) -> None:
        self.history.append(())

    def reset(self) -> None:
        self.reset_count += 1
        self.history.append(("<reset>",))


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hardware = FakeHardware()
        self.display: Display = MemoryDisplay()
        self.publisher = RecordingEventPublisher()
        self.controller = ShotDispenserController(
            hardware=self.hardware,
            display=self.display,
            timing=TimingConfig(
                message_pause_seconds=0.0,
                pvp_red_seconds=0.01,
                pvp_yellow_min_seconds=0.01,
                pvp_yellow_max_seconds=0.01,
                pvp_timeout_seconds=0.05,
                pvp_result_seconds=0.0,
                wait_tick_seconds=0.001,
                pump_max_seconds=0.2,
                pvp_blink_count=1,
                pvp_blink_seconds=0.0,
            ),
            publisher=self.publisher,
            rng=random.Random(1),
        )

    def test_pump_runs_until_release(self) -> None:
        self.assertTrue(self.controller.start_pump(1))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        self.controller.stop_pump(1)

        self.assertTrue(self.controller.join_idle())
        self.assertFalse(any(self.hardware.pumps))
        self.assertIn(("pump_started", {"pump": 1}), self.publisher.events)
        self.assertIn(("pump_stopped", {"pump": 1}), self.publisher.events)

    def test_multiple_pumps_run_concurrently(self) -> None:
        self.assertTrue(self.controller.start_pump(1))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        self.assertTrue(self.controller.start_pump(2))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[1]))

        self.assertTrue(self.hardware.pumps[0])
        self.assertTrue(self.hardware.pumps[1])

        self.controller.stop_pump(1)
        self.controller.stop_pump(2)
        self.assertTrue(self.controller.join_idle())
        self.assertFalse(any(self.hardware.pumps))

    def test_duplicate_pump_press_is_ignored(self) -> None:
        self.assertTrue(self.controller.start_pump(1))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        self.assertFalse(self.controller.start_pump(1))

        self.controller.stop_pump(1)
        self.assertTrue(self.controller.join_idle())

    def test_exclusive_action_rejected_while_pump_runs(self) -> None:
        self.assertTrue(self.controller.start_pump(1))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        self.assertFalse(self.controller.start_all_pumps())

        self.controller.stop_pump(1)
        self.assertTrue(self.controller.join_idle())

    def test_pump_safety_limit_stops_after_timeout(self) -> None:
        self.assertTrue(self.controller.start_pump(1))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        # Never release the key: the 0.2s safety cut must stop it.
        self.assertTrue(self.controller.join_idle(timeout=1.0))
        self.assertFalse(any(self.hardware.pumps))
        self.assertIn(("pump_limit", {"pump": 1}), self.publisher.events)

    def test_raffle_runs_selected_pumps(self) -> None:
        self.assertTrue(self.controller.start_raffle())
        self.assertTrue(wait_for(lambda: any(self.hardware.pumps)))

        self.controller.stop_raffle()
        self.assertTrue(self.controller.join_idle())
        self.assertFalse(any(self.hardware.pumps))
        started = [
            payload
            for name, payload in self.publisher.events
            if name == "raffle_started"
        ]
        self.assertEqual(1, len(started))
        self.assertTrue(1 <= len(started[0]["pumps"]) <= 4)

    def test_all_pumps_run_until_release(self) -> None:
        self.assertTrue(self.controller.start_all_pumps())
        self.assertTrue(wait_for(lambda: all(self.hardware.pumps)))

        self.controller.stop_all_pumps()

        self.assertTrue(self.controller.join_idle())
        self.assertFalse(any(self.hardware.pumps))
        self.assertIn(("all_pumps_started", {}), self.publisher.events)
        self.assertIn(("all_pumps_stopped", {}), self.publisher.events)

    def test_safe_stop_turns_everything_off(self) -> None:
        self.assertTrue(self.controller.start_all_pumps())
        self.assertTrue(wait_for(lambda: all(self.hardware.pumps)))

        self.controller.safe_stop("test")

        self.assertTrue(self.controller.join_idle())
        self.assertFalse(any(self.hardware.pumps))
        self.assertFalse(self.hardware.red)
        self.assertFalse(self.hardware.yellow)
        self.assertFalse(self.hardware.green)
        self.assertEqual(0, self.display.reset_count)

    def test_operator_safe_stop_resets_display(self) -> None:
        self.controller.handle_input(OperatorInput(Control.STOP_ALL, pressed=True))

        self.assertEqual(1, self.display.reset_count)
        self.assertEqual(("<reset>",), self.display.history[-2])
        self.assertEqual(
            ("JaegerMASTER".center(20), "Block Bombas", "operator", ""),
            self.display.history[-1],
        )

    def test_cleanup_uses_configured_pump_count(self) -> None:
        hardware = FakeHardware(pump_count=2)
        controller = ShotDispenserController(
            hardware=hardware,
            display=MemoryDisplay(),
            timing=TimingConfig(message_pause_seconds=0.0, wait_tick_seconds=0.001),
            pump_count=2,
        )

        self.assertTrue(controller.start_pump(1))
        self.assertTrue(wait_for(lambda: hardware.pumps[0]))
        controller.stop_pump(1)

        self.assertTrue(controller.join_idle())
        self.assertEqual([False, False], hardware.pumps)

    def test_random_pump_pool_uses_all_pumps_before_repeating(self) -> None:
        first_round = [self.controller._next_random_pump() for _ in range(4)]
        second_round = [self.controller._next_random_pump() for _ in range(4)]

        self.assertEqual({1, 2, 3, 4}, set(first_round))
        self.assertEqual({1, 2, 3, 4}, set(second_round))

    def _pass_pvp_test_phase(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self.assertTrue(
            wait_for(lambda: self.controller._pvp is not None)
        )
        self.assertTrue(self.controller.player_pressed(1))
        self.assertTrue(self.controller.player_pressed(2))

    def test_pvp_test_phase_lights_each_player_led(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self.assertTrue(wait_for(lambda: self.controller._pvp is not None))

        self.controller.player_pressed(1)
        self.assertTrue(wait_for(lambda: self.hardware.green))
        self.controller.player_pressed(2)

        self.assertTrue(self.controller.join_idle(timeout=2.0))
        self.assertIn(("pvp_started", {}), self.publisher.events)

    def test_pvp_thread_exits_before_display_when_already_done(self) -> None:
        action = RunningAction("pvp", threading.Event())
        action.stop_event.set()
        self.controller._pvp = PvpState()

        self.controller._run_pvp_game(action)

        self.assertEqual([], self.display.history)
        self.assertIn(("pvp_started", {}), self.publisher.events)

    def test_pvp_countdown_shows_red_then_yellow_then_go(self) -> None:
        self._pass_pvp_test_phase()
        self.assertTrue(self.controller.join_idle(timeout=2.0))

        center = lambda text: text.center(20)
        rows = self.display.history

        def first_row(needle: str) -> int:
            for index, row in enumerate(rows):
                if needle in row:
                    return index
            return -1

        red = first_row(center(self.controller._messages.pvp_red))
        yellow = first_row(center(self.controller._messages.pvp_yellow))
        go = first_row(center(self.controller._messages.pvp_now))
        self.assertNotEqual(-1, red)
        self.assertNotEqual(-1, yellow)
        self.assertNotEqual(-1, go)
        self.assertLess(red, yellow)
        self.assertLess(yellow, go)

    def test_pvp_right_player_wins_blinks_red(self) -> None:
        self._pass_pvp_test_phase()
        self.assertTrue(wait_for(lambda: self.controller._pvp is not None
                                 and self.controller._pvp.green_at is not None))

        self.assertTrue(self.controller.player_pressed(2))
        self.assertTrue(self.controller.player_pressed(1))

        self.assertTrue(self.controller.join_idle(timeout=2.0))
        winner_events = [
            payload
            for name, payload in self.publisher.events
            if name == "pvp_winner"
        ]
        self.assertEqual(1, len(winner_events))
        self.assertEqual(2, winner_events[0]["player"])
        self.assertTrue(self.hardware.red)
        self.assertFalse(self.hardware.green)

    def test_no_displayed_line_exceeds_screen(self) -> None:
        # Drive a full winning game (test phase, countdown, both react,
        # result with reaction times + champion line) and assert every
        # line ever shown fits the 20x4 screen.
        self._pass_pvp_test_phase()
        self.assertTrue(wait_for(lambda: self.controller._pvp is not None
                                 and self.controller._pvp.green_at is not None))
        self.assertTrue(self.controller.player_pressed(2))
        self.assertTrue(self.controller.player_pressed(1))
        self.assertTrue(self.controller.join_idle(timeout=2.0))

        # Also exercise the raffle and random pump screens.
        self.controller.start_pvp()  # leave PvP so pumps are enabled
        self.assertTrue(self.controller.start_raffle())
        self.assertTrue(wait_for(lambda: any(self.hardware.pumps)))
        self.controller.stop_raffle()
        self.assertTrue(self.controller.join_idle())

        champion_lines = [
            line
            for row in self.display.history
            for line in row
            if "Campeao 1h:" in line
        ]
        self.assertTrue(champion_lines, "champion line should appear post-game")
        for row in self.display.history:
            for line in row:
                self.assertLessEqual(
                    len(line), 20, f"line exceeds 20 cols: {line!r}"
                )
            self.assertLessEqual(len(row), 4, f"too many rows: {row!r}")

    def test_pvp_left_player_wins_blinks_green(self) -> None:
        self._pass_pvp_test_phase()
        self.assertTrue(wait_for(lambda: self.controller._pvp is not None
                                 and self.controller._pvp.green_at is not None))

        self.assertTrue(self.controller.player_pressed(1))
        self.assertTrue(self.controller.player_pressed(2))

        self.assertTrue(self.controller.join_idle(timeout=2.0))
        self.assertTrue(self.hardware.green)
        self.assertFalse(self.hardware.red)
        self.assertIsNotNone(self.controller.champion_ms())

    def test_pvp_timeout_returns_to_ready_state(self) -> None:
        self._pass_pvp_test_phase()

        self.assertTrue(self.controller.join_idle(timeout=2.0))

        self.assertFalse(self.hardware.red)
        self.assertFalse(self.hardware.yellow)
        self.assertFalse(self.hardware.green)
        self.assertIn(("pvp_timeout", {}), self.publisher.events)

    def test_kp8_exits_finished_game_and_enables_pumps(self) -> None:
        self._pass_pvp_test_phase()
        self.assertTrue(self.controller.join_idle(timeout=2.0))
        self.assertEqual(PVP_DONE, self.controller._pvp.phase)

        # While the result is on screen, pumps are blocked.
        self.assertFalse(self.controller.start_pump(1))

        # KP8 acknowledges the result, leaves PvP and re-enables pouring.
        self.assertTrue(self.controller.start_pvp())
        self.assertIsNone(self.controller._pvp)
        self.assertEqual(self.controller._messages.main_art, self.display.history[-1])

        self.assertTrue(self.controller.start_pump(1))
        self.controller.stop_pump(1)
        self.assertTrue(self.controller.join_idle())

    def test_kp8_from_idle_starts_a_fresh_game(self) -> None:
        self._pass_pvp_test_phase()
        self.assertTrue(self.controller.join_idle(timeout=2.0))
        self.assertTrue(self.controller.start_pvp())  # exit
        self.assertIsNone(self.controller._pvp)

        self.assertTrue(self.controller.start_pvp())  # fresh game
        self.assertTrue(wait_for(lambda: self.controller._pvp is not None))
        self.assertTrue(self.controller.player_pressed(1))
        self.assertTrue(self.controller.player_pressed(2))
        self.assertTrue(self.controller.join_idle(timeout=2.0))

    def test_pvp_false_start_during_red_is_immediate(self) -> None:
        slow = ShotDispenserController(
            hardware=self.hardware,
            display=self.display,
            timing=TimingConfig(
                message_pause_seconds=0.0,
                pvp_red_seconds=5.0,
                pvp_yellow_min_seconds=5.0,
                pvp_yellow_max_seconds=5.0,
                pvp_timeout_seconds=5.0,
                pvp_result_seconds=0.0,
                wait_tick_seconds=0.001,
                pvp_blink_count=1,
                pvp_blink_seconds=0.0,
            ),
            publisher=self.publisher,
            rng=random.Random(1),
        )
        self.assertTrue(slow.start_pvp())
        slow.player_pressed(1)
        slow.player_pressed(2)
        self.assertTrue(
            wait_for(lambda: slow._pvp is not None
                     and slow._pvp.phase == "countdown")
        )

        slow.player_pressed(1)  # jump the gun during the long red stage

        self.assertTrue(slow.join_idle(timeout=2.0))
        self.assertIn(("pvp_false_start", {"player": 1}), self.publisher.events)
        self.assertEqual(PVP_DONE, slow._pvp.phase)


def wait_for(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


if __name__ == "__main__":
    unittest.main()
