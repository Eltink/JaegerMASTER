from __future__ import annotations

import errno
import threading
from dataclasses import dataclass
from select import select
from typing import Callable

from .commands import Control, OperatorInput
from .config import NumpadConfig


KEY_RELEASED = 0
KEY_PRESSED = 1
KEY_REPEATED = 2


@dataclass(frozen=True)
class InputDeviceInfo:
    path: str
    name: str
    physical_location: str
    supported_keys: tuple[str, ...]


class NumpadKeyMapper:
    def __init__(self, key_bindings: dict[str, Control]) -> None:
        self._key_bindings = dict(key_bindings)
        self._pressed_keys: set[str] = set()

    @property
    def expected_key_names(self) -> tuple[str, ...]:
        return tuple(self._key_bindings)

    def map_key_event(self, key_name: str, value: int) -> OperatorInput | None:
        control = self._key_bindings.get(key_name)
        if control is None:
            return None
        if value == KEY_PRESSED:
            if key_name in self._pressed_keys:
                return None
            self._pressed_keys.add(key_name)
            return OperatorInput(control, pressed=True)
        if value == KEY_RELEASED:
            if key_name not in self._pressed_keys:
                return None
            self._pressed_keys.remove(key_name)
            return OperatorInput(control, pressed=False)
        if value == KEY_REPEATED:
            return None
        raise ValueError(f"Unexpected key value {value!r} for {key_name}")


class EvdevNumpadInput:
    def __init__(
        self,
        config: NumpadConfig,
        mapper: NumpadKeyMapper,
        callback: Callable[[OperatorInput], None],
    ) -> None:
        self._config = config
        self._mapper = mapper
        self._callback = callback

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        evdev = _load_evdev()
        stop_event = stop_event or threading.Event()
        device = self._open_device(evdev)

        grabbed = False
        try:
            if self._config.grab_input:
                device.grab()
                grabbed = True

            while not stop_event.is_set():
                try:
                    ready, _, _ = select([device.fd], [], [], 0.1)
                    if not ready:
                        continue
                    for event in device.read():
                        if event.type != evdev.ecodes.EV_KEY:
                            continue
                        key_name = _key_name(evdev, event.code)
                        operator_input = self._mapper.map_key_event(
                            key_name,
                            event.value,
                        )
                        if operator_input is not None:
                            self._callback(operator_input)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    if exc.errno == errno.ENODEV:
                        raise RuntimeError(
                            "The input device disconnected. Hardware has been stopped; "
                            "reconnect the keyboard and restart the app."
                        ) from exc
                    raise
        finally:
            if grabbed:
                try:
                    device.ungrab()
                except OSError:
                    pass
            device.close()

    def _open_device(self, evdev):
        if self._config.device_path:
            return evdev.InputDevice(self._config.device_path)

        candidates = find_candidate_devices(
            self._mapper.expected_key_names,
            name_contains=self._config.device_name_contains,
        )
        if not candidates:
            raise RuntimeError(
                "No Bluetooth numpad was found. Pair the numpad and run "
                "`python3 main.py --list-input-devices` to find its event path."
            )
        if len(candidates) > 1:
            paths = ", ".join(device.path for device in candidates)
            raise RuntimeError(
                "More than one keyboard-like input device matched. Re-run with "
                f"`--numpad-device PATH`. Candidates: {paths}"
            )
        return evdev.InputDevice(candidates[0].path)


def list_input_devices() -> list[InputDeviceInfo]:
    evdev = _load_evdev()
    devices: list[InputDeviceInfo] = []
    for path in evdev.list_devices():
        device = evdev.InputDevice(path)
        try:
            devices.append(_device_info(evdev, device))
        finally:
            device.close()
    return devices


def find_candidate_devices(
    expected_key_names: tuple[str, ...],
    name_contains: str | None = None,
) -> list[InputDeviceInfo]:
    expected = set(expected_key_names)
    candidates: list[InputDeviceInfo] = []
    for info in list_input_devices():
        if name_contains and name_contains.lower() not in info.name.lower():
            continue
        supported = set(info.supported_keys)
        if expected.intersection(supported):
            candidates.append(info)
    return candidates


def _device_info(evdev, device) -> InputDeviceInfo:
    key_codes = device.capabilities().get(evdev.ecodes.EV_KEY, [])
    key_names = sorted(_key_name(evdev, code) for code in key_codes)
    return InputDeviceInfo(
        path=device.path,
        name=device.name,
        physical_location=device.phys,
        supported_keys=tuple(key_names),
    )


def _key_name(evdev, code: int) -> str:
    name = evdev.ecodes.KEY.get(code, f"KEY_CODE_{code}")
    if isinstance(name, (list, tuple)):
        return str(name[0])
    return str(name)


def _load_evdev():
    try:
        import evdev
    except ImportError as exc:
        raise RuntimeError(
            "The evdev package is required for Bluetooth numpad input. Install it "
            "with `sudo apt install python3-evdev` or `pip install evdev`."
        ) from exc
    return evdev
