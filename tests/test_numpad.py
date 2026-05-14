from __future__ import annotations

import unittest

from shot_dispenser.commands import Control
from shot_dispenser.numpad import (
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


if __name__ == "__main__":
    unittest.main()
