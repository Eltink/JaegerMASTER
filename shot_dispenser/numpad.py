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


@dataclass
class _OpenInputDevice:
    device: object
    mapper: NumpadKeyMapper
    grabbed: bool = False


class NumpadKeyMapper:
    def __init__(
        self,
        key_bindings: dict[str, Control],
        shutdown_chord: tuple[str, ...] = ("KEY_BACKSPACE", "KEY_KP0"),
        restart_chord: tuple[str, ...] = ("KEY_KP0", "KEY_BACKSPACE", "KEY_KPENTER"),
    ) -> None:
        self._key_bindings = dict(key_bindings)
        self._shutdown_chord = frozenset(shutdown_chord)
        self._restart_chord = frozenset(restart_chord)
        self._pressed_keys: set[str] = set()
        self._pressed_control_keys: set[str] = set()
        self._shutdown_chord_active = False
        self._restart_chord_active = False

    @property
    def expected_key_names(self) -> tuple[str, ...]:
        return tuple(self._key_bindings)

    def map_key_event(self, key_name: str, value: int) -> OperatorInput | None:
        control = self._key_bindings.get(key_name)
        in_shutdown_chord = key_name in self._shutdown_chord
        in_restart_chord = key_name in self._restart_chord

        if control is None and not in_shutdown_chord and not in_restart_chord:
            return None

        if value == KEY_PRESSED:
            if key_name in self._pressed_keys:
                return None
            self._pressed_keys.add(key_name)

            # Restart chord (3-key) takes priority over shutdown chord (2-key).
            # Fires when all restart keys are held, suppressing any pending shutdown.
            if self._restart_chord and self._restart_chord.issubset(self._pressed_keys):
                if not self._restart_chord_active:
                    self._restart_chord_active = True
                    self._shutdown_chord_active = True  # prevent double-fire
                    return OperatorInput(Control.RESTART, pressed=True)
                return None

            # Shutdown chord fires only when KPENTER (restart-exclusive key) is not held,
            # ensuring restart keys don't accidentally trigger shutdown mid-press.
            restart_exclusive = self._restart_chord - self._shutdown_chord
            if (
                self._shutdown_chord
                and self._shutdown_chord.issubset(self._pressed_keys)
                and not self._shutdown_chord_active
                and not restart_exclusive.intersection(self._pressed_keys)
            ):
                self._shutdown_chord_active = True
                return OperatorInput(Control.SHUTDOWN, pressed=True)

            if control is None:
                return None
            self._pressed_control_keys.add(key_name)
            return OperatorInput(control, pressed=True)

        if value == KEY_RELEASED:
            if key_name not in self._pressed_keys:
                return None
            self._pressed_keys.remove(key_name)
            if self._shutdown_chord_active and not self._shutdown_chord.issubset(self._pressed_keys):
                self._shutdown_chord_active = False
            if self._restart_chord_active and not self._restart_chord.issubset(self._pressed_keys):
                self._restart_chord_active = False
            if key_name not in self._pressed_control_keys:
                return None
            self._pressed_control_keys.remove(key_name)
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
        devices = self._open_devices(evdev)

        try:
            if self._config.grab_input:
                for entry in devices:
                    entry.device.grab()
                    entry.grabbed = True

            while not stop_event.is_set():
                try:
                    ready, _, _ = select(
                        [entry.device.fd for entry in devices],
                        [],
                        [],
                        0.1,
                    )
                    if not ready:
                        continue
                    device_by_fd = {entry.device.fd: entry for entry in devices}
                    for fd in ready:
                        entry = device_by_fd.get(fd)
                        if entry is not None:
                            self._read_ready_device(evdev, entry)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    if exc.errno == errno.ENODEV:
                        raise RuntimeError(
                            "An input device disconnected. Hardware has been stopped; "
                            "reconnect the keyboard and restart the app."
                        ) from exc
                    raise
        finally:
            for entry in devices:
                self._close_device(entry)

    def _read_ready_device(self, evdev, entry: _OpenInputDevice) -> None:
        for event in entry.device.read():
            if event.type != evdev.ecodes.EV_KEY:
                continue
            key_name = _key_name(evdev, event.code)
            operator_input = entry.mapper.map_key_event(
                key_name,
                event.value,
            )
            if operator_input is not None:
                self._callback(operator_input)

    def _open_devices(self, evdev) -> list[_OpenInputDevice]:
        if self._config.device_path:
            return [
                _OpenInputDevice(
                    evdev.InputDevice(self._config.device_path),
                    self._new_mapper(),
                )
            ]

        candidates = find_candidate_devices(
            self._mapper.expected_key_names,
            name_contains=self._config.device_name_contains,
        )
        if not candidates:
            raise RuntimeError(
                "No Bluetooth numpad was found. Pair the numpad and run "
                "`python3 main.py --list-input-devices` to find its event path."
            )
        return [
            _OpenInputDevice(evdev.InputDevice(candidate.path), self._new_mapper())
            for candidate in candidates
        ]

    def _new_mapper(self) -> NumpadKeyMapper:
        return NumpadKeyMapper(
            self._config.key_bindings,
            self._config.shutdown_chord,
            self._config.restart_chord,
        )

    def _close_device(self, entry: _OpenInputDevice) -> None:
        if entry.grabbed:
            try:
                entry.device.ungrab()
            except OSError:
                pass
        entry.device.close()


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
