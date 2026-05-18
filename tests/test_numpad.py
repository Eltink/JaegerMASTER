from __future__ import annotations

import unittest
from unittest.mock import patch

from shot_dispenser.commands import Control
from shot_dispenser.config import NumpadConfig
from shot_dispenser.numpad import (
    EvdevNumpadInput,
    InputDeviceInfo,
    KEY_PRESSED,
    KEY_RELEASED,
    KEY_REPEATED,
    NumpadKeyMapper,
    _key_name,
)


class NumpadKeyMapperTests(unittest.TestCase):
    def test_maps_key_down_and_key_up(self) -> None:
        mapper = NumpadKeyMapper({"KEY_KP1": Control.PUMP_1})

        pressed = mapper.map_key_event("KEY_KP1", KEY_PRESSED)
        released = mapper.map_key_event("KEY_KP1", KEY_RELEASED)

        self.assertIsNotNone(pressed)
        self.assertIsNotNone(released)
        assert pressed is not None
        assert released is not None
        self.assertEqual(Control.PUMP_1, pressed.control)
        self.assertTrue(pressed.pressed)
        self.assertEqual(Control.PUMP_1, released.control)
        self.assertTrue(released.released)

    def test_ignores_repeat_and_unknown_keys(self) -> None:
        mapper = NumpadKeyMapper({"KEY_KP1": Control.PUMP_1})

        self.assertIsNone(mapper.map_key_event("KEY_KP1", KEY_REPEATED))
        self.assertIsNone(mapper.map_key_event("KEY_A", KEY_PRESSED))

    def test_debounces_duplicate_key_down_and_release(self) -> None:
        mapper = NumpadKeyMapper({"KEY_KP1": Control.PUMP_1})

        self.assertIsNotNone(mapper.map_key_event("KEY_KP1", KEY_PRESSED))
        self.assertIsNone(mapper.map_key_event("KEY_KP1", KEY_PRESSED))
        self.assertIsNotNone(mapper.map_key_event("KEY_KP1", KEY_RELEASED))
        self.assertIsNone(mapper.map_key_event("KEY_KP1", KEY_RELEASED))

    def test_maps_backspace_and_zero_chord_to_shutdown(self) -> None:
        mapper = NumpadKeyMapper({"KEY_KP0": Control.STOP_ALL})

        self.assertIsNone(mapper.map_key_event("KEY_BACKSPACE", KEY_PRESSED))
        shutdown = mapper.map_key_event("KEY_KP0", KEY_PRESSED)

        self.assertIsNotNone(shutdown)
        assert shutdown is not None
        self.assertEqual(Control.SHUTDOWN, shutdown.control)
        self.assertTrue(shutdown.pressed)
        self.assertIsNone(mapper.map_key_event("KEY_KP0", KEY_RELEASED))

    def test_maps_zero_then_backspace_to_shutdown(self) -> None:
        mapper = NumpadKeyMapper({"KEY_KP0": Control.STOP_ALL})

        stop = mapper.map_key_event("KEY_KP0", KEY_PRESSED)
        shutdown = mapper.map_key_event("KEY_BACKSPACE", KEY_PRESSED)

        self.assertIsNotNone(stop)
        self.assertIsNotNone(shutdown)
        assert stop is not None
        assert shutdown is not None
        self.assertEqual(Control.STOP_ALL, stop.control)
        self.assertEqual(Control.SHUTDOWN, shutdown.control)

    def test_maps_backspace_and_enter_chord_to_restart(self) -> None:
        mapper = NumpadKeyMapper({"KEY_KPENTER": Control.STOP_ALL})

        self.assertIsNone(mapper.map_key_event("KEY_BACKSPACE", KEY_PRESSED))
        restart = mapper.map_key_event("KEY_KPENTER", KEY_PRESSED)

        self.assertIsNotNone(restart)
        assert restart is not None
        self.assertEqual(Control.RESTART, restart.control)
        self.assertTrue(restart.pressed)
        self.assertIsNone(mapper.map_key_event("KEY_KPENTER", KEY_RELEASED))

    def test_enter_alone_is_still_stop_all(self) -> None:
        mapper = NumpadKeyMapper({"KEY_KPENTER": Control.STOP_ALL})

        pressed = mapper.map_key_event("KEY_KPENTER", KEY_PRESSED)

        self.assertIsNotNone(pressed)
        assert pressed is not None
        self.assertEqual(Control.STOP_ALL, pressed.control)

    def test_rejects_unexpected_key_value(self) -> None:
        mapper = NumpadKeyMapper({"KEY_KP1": Control.PUMP_1})

        with self.assertRaises(ValueError):
            mapper.map_key_event("KEY_KP1", 99)

    def test_key_name_normalizes_alias_tuples(self) -> None:
        class FakeEcodes:
            KEY = {1: ("KEY_SCREENLOCK", "KEY_COFFEE")}

        class FakeEvdev:
            ecodes = FakeEcodes()

        self.assertEqual("KEY_SCREENLOCK", _key_name(FakeEvdev, 1))


class EvdevNumpadInputTests(unittest.TestCase):
    def test_opens_all_matching_devices(self) -> None:
        config = NumpadConfig()
        runner = EvdevNumpadInput(
            config,
            NumpadKeyMapper(config.key_bindings, config.shutdown_chord),
            lambda _operator_input: None,
        )
        candidates = [
            InputDeviceInfo("/dev/input/event4", "Keyboard A", "", ("KEY_KP1",)),
            InputDeviceInfo("/dev/input/event9", "Keyboard B", "", ("KEY_KP1",)),
        ]

        with patch("shot_dispenser.numpad.find_candidate_devices", return_value=candidates):
            devices = runner._open_devices(FakeEvdev)

        self.assertEqual(["/dev/input/event4", "/dev/input/event9"], [
            entry.device.path for entry in devices
        ])
        self.assertEqual(2, len({id(entry.mapper) for entry in devices}))

    def test_explicit_device_path_opens_only_that_device(self) -> None:
        config = NumpadConfig(device_path="/dev/input/event4")
        runner = EvdevNumpadInput(
            config,
            NumpadKeyMapper(config.key_bindings, config.shutdown_chord),
            lambda _operator_input: None,
        )

        devices = runner._open_devices(FakeEvdev)

        self.assertEqual(["/dev/input/event4"], [entry.device.path for entry in devices])


class FakeInputDevice:
    def __init__(self, path: str) -> None:
        self.path = path


class FakeEvdev:
    @staticmethod
    def InputDevice(path: str) -> FakeInputDevice:
        return FakeInputDevice(path)


if __name__ == "__main__":
    unittest.main()
