from __future__ import annotations

import random
import time
import unittest

from shot_dispenser.commands import Control, OperatorInput
from shot_dispenser.config import TimingConfig
from shot_dispenser.controller import ShotDispenserController
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

    def backlight_off(self) -> None:
        self.history.append(("<backlight off>",))


_FAST_TIMING = TimingConfig(
    message_pause_seconds=0.0,
    pvp_red_seconds=0.01,
    pvp_yellow_min_seconds=0.01,
    pvp_yellow_max_seconds=0.01,
    pvp_timeout_seconds=0.03,
    pvp_result_seconds=0.0,
    pvp_blink_count=1,
    pvp_blink_seconds=0.0,
    pump_max_seconds=5.0,
    wait_tick_seconds=0.001,
)


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hardware = FakeHardware()
        self.display: Display = MemoryDisplay()
        self.publisher = RecordingEventPublisher()
        self.controller = ShotDispenserController(
            hardware=self.hardware,
            display=self.display,
            timing=_FAST_TIMING,
            publisher=self.publisher,
            rng=random.Random(1),
        )

    # ── Pump / multi-pump tests ────────────────────────────────────────────

    def test_pump_runs_until_release(self) -> None:
        self.assertTrue(self.controller.start_pump(1))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        self.controller.stop_pump(1)

        self.assertTrue(self.controller.join_idle())
        self.assertFalse(any(self.hardware.pumps))
        self.assertIn(("pump_started", {"pump": 1}), self.publisher.events)
        self.assertIn(("pump_stopped", {"pump": 1}), self.publisher.events)

    def test_two_pumps_run_simultaneously(self) -> None:
        self.assertTrue(self.controller.start_pump(1))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        # Second pump should also start — multi-pump is supported now
        self.assertTrue(self.controller.start_pump(2))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[1]))

        self.controller.stop_pump(1)
        self.controller.stop_pump(2)

        self.assertTrue(self.controller.join_idle())
        self.assertFalse(any(self.hardware.pumps))

    def test_starting_same_pump_twice_is_ignored(self) -> None:
        self.assertTrue(self.controller.start_pump(1))
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        # Second start of same pump is silently ignored (not double-started)
        self.assertFalse(self.controller.start_pump(1))
        self.assertEqual(1, self.hardware.log.count("pump_1_on"))

        self.controller.stop_pump(1)
        self.assertTrue(self.controller.join_idle())

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
            ("    JaegerMASTER    ", "Block Bombas", "operator", ""),
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

    def test_pump_rejected_during_pvp_game(self) -> None:
        self.controller.start_pvp()
        # Complete setup so PvP game is active
        self.controller.player_pressed(1)
        self.controller.player_pressed(2)
        # Now a pump press should be rejected with busy
        result = self.controller.start_pump(1)
        self.assertFalse(result)

    # ── PvP tests ─────────────────────────────────────────────────────────

    def _complete_pvp_setup(self) -> None:
        """Complete the setup phase so the countdown starts."""
        self.controller.player_pressed(1)
        self.controller.player_pressed(2)

    def test_pvp_false_start_resets_to_safe_state(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self._complete_pvp_setup()

        # Press immediately (before green light) → false start
        self.assertTrue(self.controller.player_pressed(1))

        self.assertTrue(self.controller.join_idle())
        self.assertFalse(self.hardware.red)
        self.assertFalse(self.hardware.yellow)
        self.assertFalse(self.hardware.green)
        self.assertIn(("pvp_false_start", {"player": 1}), self.publisher.events)

    def test_pvp_setup_requires_both_players(self) -> None:
        self.assertTrue(self.controller.start_pvp())

        # Only player 1 presses — PvP should still be active (waiting for P2)
        self.controller.player_pressed(1)
        self.assertTrue(self.controller._pvp_active)
        self.assertTrue(self.controller._pvp_in_setup)

        # Player 2 presses — setup complete, countdown starts
        self.controller.player_pressed(2)
        self.assertFalse(self.controller._pvp_in_setup)

    def test_pvp_thread_exits_before_display_when_already_done(self) -> None:
        self.controller._pvp_done.set()

        self.controller._run_pvp_game()

        self.assertEqual([], self.display.history)
        self.assertIn(("pvp_started", {}), self.publisher.events)

    def test_pvp_turns_red_on_before_yellow_and_green(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self._complete_pvp_setup()

        self.assertTrue(wait_for(lambda: "red_on" in self.hardware.log))
        self.assertTrue(wait_for(lambda: "yellow_on" in self.hardware.log))
        self.assertTrue(wait_for(lambda: "green_on" in self.hardware.log))

        self.assertLess(self.hardware.log.index("red_on"), self.hardware.log.index("yellow_on"))
        self.assertLess(self.hardware.log.index("yellow_on"), self.hardware.log.index("green_on"))

        self.assertTrue(self.controller.join_idle(timeout=1.0))

    def test_pvp_right_player_wins_after_green(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self._complete_pvp_setup()
        self.assertTrue(wait_for(lambda: self.hardware.green))

        self.assertTrue(self.controller.player_pressed(2))

        self.assertTrue(self.controller.join_idle())
        self.assertFalse(self.hardware.red)
        self.assertFalse(self.hardware.yellow)
        self.assertFalse(self.hardware.green)
        self.assertIn("pvp_winner", [e[0] for e in self.publisher.events])
        winner_event = next(e for e in self.publisher.events if e[0] == "pvp_winner")
        self.assertEqual(2, winner_event[1]["player"])

    def test_pvp_left_player_wins_uses_green_led(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self._complete_pvp_setup()
        self.assertTrue(wait_for(lambda: self.hardware.green))

        self.assertTrue(self.controller.player_pressed(1))

        self.assertTrue(self.controller.join_idle())
        # Left player = green LED winner (blink_green called)
        self.assertIn("green_on", self.hardware.log)

    def test_pvp_timeout_returns_to_ready_state(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self._complete_pvp_setup()

        self.assertTrue(self.controller.join_idle(timeout=1.0))

        self.assertFalse(self.hardware.red)
        self.assertFalse(self.hardware.yellow)
        self.assertFalse(self.hardware.green)
        self.assertIn(("pvp_timeout", {}), self.publisher.events)

    def test_pvp_records_reaction_time_on_win(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self._complete_pvp_setup()
        self.assertTrue(wait_for(lambda: self.hardware.green))

        self.controller.player_pressed(2)
        self.assertTrue(self.controller.join_idle())

        winner_events = [e for e in self.publisher.events if e[0] == "pvp_winner"]
        self.assertTrue(winner_events)
        self.assertIn("ms", winner_events[0][1])
        self.assertGreater(winner_events[0][1]["ms"], 0)

    def test_pvp_champion_updated_on_win(self) -> None:
        self.assertTrue(self.controller.start_pvp())
        self._complete_pvp_setup()
        self.assertTrue(wait_for(lambda: self.hardware.green))

        self.controller.player_pressed(1)
        self.assertTrue(self.controller.join_idle())

        self.assertIsNotNone(self.controller._pvp_champion_ms)

    def test_pvp_not_startable_during_pump(self) -> None:
        self.controller.start_pump(1)
        self.assertTrue(wait_for(lambda: self.hardware.pumps[0]))

        self.assertFalse(self.controller.start_pvp())

        self.controller.stop_pump(1)
        self.assertTrue(self.controller.join_idle())

    # ── Lottery tests ─────────────────────────────────────────────────────

    def test_lottery_starts_at_least_one_pump(self) -> None:
        self.assertTrue(self.controller.start_lottery())
        self.assertTrue(wait_for(lambda: any(self.hardware.pumps)))

        self.controller.stop_lottery()
        self.assertTrue(self.controller.join_idle())
        self.assertFalse(any(self.hardware.pumps))

    def test_lottery_event_recorded(self) -> None:
        self.assertTrue(self.controller.start_lottery())
        self.assertTrue(wait_for(lambda: any(self.hardware.pumps)))
        self.controller.stop_lottery()
        self.assertTrue(self.controller.join_idle())

        self.assertIn("lottery_started", [e[0] for e in self.publisher.events])


def wait_for(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


if __name__ == "__main__":
    unittest.main()
