from __future__ import annotations

import random
import time
import unittest

from shot_dispenser.commands import Control, OperatorInput
from shot_dispenser.config import TimingConfig
from shot_dispenser.controller import RunningAction, ShotDispenserController
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
                pvp_timeout_seconds=0.03,
                pvp_result_seconds=0.0,
                wait_tick_seconds=0.001,
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

    def test_overlapping_actions_are_rejected(self) -> None:
        self.assertTrue(self.controller.start_pump(1))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        self.assertFalse(self.controller.start_pump(2))

        self.controller.stop_pump(1)
        self.assertTrue(self.controller.join_idle())
        self.assertNotIn("pump_2_on", self.hardware.log)

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
            ("Mystery Shot Box", "Parada segura", "operator", ""),
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

    def test_pvp_false_start_resets_to_safe_state(self) -> None:
        self.assertTrue(self.controller.start_pvp())

        self.assertTrue(self.controller.player_pressed(1))

        self.assertTrue(self.controller.join_idle())
        self.assertFalse(self.hardware.red)
        self.assertFalse(self.hardware.yellow)
        self.assertFalse(self.hardware.green)
        self.assertIn(("pvp_false_start", {"player": 1}), self.publisher.events)

    def test_pvp_thread_exits_before_display_when_already_done(self) -> None:
        action = RunningAction("pvp", self.controller._pvp_done)
        self.controller._pvp_done.set()

        self.controller._run_pvp_game(action)

        self.assertEqual([], self.display.history)
        self.assertIn(("pvp_started", {}), self.publisher.events)

    def test_pvp_turns_red_on_before_yellow_and_green(self) -> None:
        self.assertTrue(self.controller.start_pvp())

        self.assertTrue(wait_for(lambda: "red_on" in self.hardware.log))
        self.assertTrue(wait_for(lambda: "yellow_on" in self.hardware.log))
        self.assertTrue(wait_for(lambda: "green_on" in self.hardware.log))

        self.assertLess(self.hardware.log.index("red_on"), self.hardware.log.index("yellow_on"))
        self.assertLess(self.hardware.log.index("yellow_on"), self.hardware.log.index("green_on"))

        self.assertTrue(self.controller.join_idle(timeout=1.0))

    def test_pvp_right_player_wins_after_green(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self.assertTrue(wait_for(lambda: self.hardware.green))

        self.assertTrue(self.controller.player_pressed(2))

        self.assertTrue(self.controller.join_idle())
        self.assertFalse(self.hardware.red)
        self.assertFalse(self.hardware.yellow)
        self.assertTrue(self.hardware.green)
        self.assertIn(("pvp_winner", {"player": 2}), self.publisher.events)

    def test_pvp_timeout_returns_to_ready_state(self) -> None:
        self.assertTrue(self.controller.start_pvp())

        self.assertTrue(self.controller.join_idle(timeout=1.0))

        self.assertFalse(self.hardware.red)
        self.assertFalse(self.hardware.yellow)
        self.assertFalse(self.hardware.green)
        self.assertIn(("pvp_timeout", {}), self.publisher.events)


def wait_for(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


if __name__ == "__main__":
    unittest.main()
