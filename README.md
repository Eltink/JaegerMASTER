# Shot Dispenser

Raspberry Pi 4 firmware for a four-pump shot dispenser with a PvP reaction game, a traffic-light LED set, a 20x4 I2C LCD, and standard keyboard/numpad input through Linux `evdev`.

The canonical entry point is `main.py`, backed by the `shot_dispenser/` package. The old flat scripts are retained only for reference/hardware bring-up and still use the earlier valve/shared-pump wiring model.

## Hardware

| Component | Details |
|---|---|
| Controller | Raspberry Pi 4 Model B |
| Pumps | 4x drink pumps via relay module, one hose per drink |
| Display | 20x4 LCD with I2C adapter (PCF8574) |
| LEDs | Traffic light: red, yellow, green with shared GND |
| Operator input | Standard HID keyboard/numpad; tested with Logitech MX Keys |

## Wiring

### Pump relay outputs

The canonical app follows the fixed channel pinout from the 4-channel Raspberry Pi relay HAT. The relay HAT is active-low: GPIO HIGH keeps a relay off, GPIO LOW turns a relay on. The default code uses `active_high=False` and `initial_value=False` so pumps stay off at startup.

Temporary hand-wired relay modules can use the same GPIO pins. If a temporary module is active-high, start the app with `--pump-active-high`. When the relay HAT arrives, remove that flag or use `--pump-active-low`.

| Physical pin | GPIO | Function |
|---|---|---|
| 37 | GPIO26 | Pump 1 / relay CH1 |
| 35 | GPIO19 | Pump 2 / relay CH2 |
| 33 | GPIO13 | Pump 3 / relay CH3 |
| 31 | GPIO6 | Pump 4 / relay CH4 |

### Traffic light

| Physical pin | GPIO | Function |
|---|---|---|
| 36 | GPIO16 | Red |
| 38 | GPIO20 | Yellow |
| 40 | GPIO21 | Green |
| 39 | GND | Shared LED ground |

### Display

| Physical pin | Function |
|---|---|
| Pin 3 / GPIO2 | SDA |
| Pin 5 / GPIO3 | SCL |
| Pin 4 | 5V |
| Pin 6 | GND |

## Numpad controls

Pump actions start on key down and stop on key release. Repeated key events while a key is held are ignored. By default the app listens to every connected keyboard-like input device that exposes the configured keypad keys.

| Key | Function |
|---|---|
| KP1 | Pump 1 while held |
| KP2 | Pump 2 while held |
| KP3 | Pump 3 while held |
| KP4 | Pump 4 while held |
| KP5 | Random pump while held; all four pumps are selected once before repeats |
| KP6 | All pumps while held |
| KP7 | Start or restart PvP mode |
| KP8 | PvP left player |
| KP9 | PvP right player |
| KP0 or KP Enter | Safe stop and LCD reinitialize |
| Backspace + KP0 | Safe stop, then run the configured shutdown command |

## Software setup on the Raspberry Pi

```bash
sudo apt update
sudo apt install python3-gpiozero python3-smbus i2c-tools python3-evdev -y
pip install RPLCD --break-system-packages
sudo raspi-config   # Interface Options -> I2C -> Enable
sudo reboot
```

Verify the LCD address:

```bash
i2cdetect -y 1
```

The default LCD address is `0x27`. If the display appears at `0x3f`, pass `--lcd-address 0x3f`.

List visible Linux input devices:

```bash
python3 main.py --list-input-devices
```

Run the dispenser with an explicit event path:

```bash
python3 main.py --numpad-device /dev/input/eventX
```

Or run by device-name filter:

```bash
python3 main.py --numpad-name Logitech
```

If the Pi user cannot read `/dev/input/event*`, add it to the `input` group and log out/in:

```bash
sudo usermod -aG input "$USER"
```

## Fresh Pi instance checklist

These are the manual system changes needed on a new SD card or replacement Pi after the base Raspberry Pi OS image boots.

### Persistent WiFi and SSH

Do not rely only on Raspberry Pi Imager or boot-partition cloud-init WiFi seed files after first boot. Create a persistent NetworkManager connection on the root filesystem:

```bash
sudo nmcli radio wifi on
sudo nmcli dev wifi connect "RageCage" password "<wifi-password>"
sudo nmcli connection modify RageCage connection.autoconnect yes
sudo systemctl enable ssh.service
sudo systemctl restart ssh.service
```

Verify:

```bash
nmcli connection show RageCage
ip addr show wlan0
systemctl status ssh.service
```

Set the hostname used for mDNS/router lookup:

```bash
sudo hostnamectl hostname jaegermeister
```

The target Pi has used these interface MAC addresses:

| Interface | MAC |
|---|---|
| eth0 | `dc:a6:32:d3:44:9e` |
| wlan0 | `dc:a6:32:d3:44:9f` |

If configuring the SD card offline through `/boot/firmware/user-data`, change `/boot/firmware/meta-data` to a new `instance-id` so cloud-init treats the next boot as a new instance. Otherwise once-per-instance cloud-init modules will not rewrite network files.

### Application deployment

The live code is expected at `/home/pi/JaegerMASTER-live-test`:

```bash
sudo install -d -o pi -g pi /home/pi/JaegerMASTER-live-test
rsync -a --delete ./ pi@<pi-ip>:/home/pi/JaegerMASTER-live-test/
```

The service content is in the "Autostart on boot" section. Enable and restart it only after the package install and poweroff sudoers rule are in place.

Install runtime packages:

```bash
sudo apt update
sudo apt install python3-gpiozero python3-smbus i2c-tools python3-evdev -y
python3 -m pip install RPLCD --break-system-packages
```

Enable I2C and verify the LCD:

```bash
sudo raspi-config   # Interface Options -> I2C -> Enable
i2cdetect -y 1      # expected LCD address: 0x27
```

### Poweroff permission

Backspace + KP0 calls `/usr/sbin/poweroff` through sudo. Allow the service user to run only that command without a password:

```bash
echo 'pi ALL=(root) NOPASSWD: /usr/sbin/poweroff' | sudo tee /etc/sudoers.d/shotdispenser-poweroff
sudo chown root:root /etc/sudoers.d/shotdispenser-poweroff
sudo chmod 0440 /etc/sudoers.d/shotdispenser-poweroff
sudo visudo -cf /etc/sudoers.d/shotdispenser-poweroff
```

### Solid ACT LED while running

The Pi's built-in green ACT LED is not a power LED. This service makes it solid while Linux is running and turns it off during shutdown:

```ini
[Unit]
Description=Set Raspberry Pi ACT LED solid while Linux is running
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo default-on > /sys/class/leds/ACT/trigger'
ExecStop=/bin/sh -c 'echo none > /sys/class/leds/ACT/trigger; echo 0 > /sys/class/leds/ACT/brightness'
RemainAfterExit=yes
TimeoutStopSec=2

[Install]
WantedBy=multi-user.target
```

Install it as `/etc/systemd/system/act-led-solid.service`:

```bash
sudo systemctl daemon-reload
sudo systemctl enable act-led-solid.service
sudo systemctl restart act-led-solid.service
```

## Development commands

Syntax-only validation that is safe off the Pi:

```bash
python3 -m py_compile main.py Alles_Dabei.py Pumpe_und_Ventile.py ventil_toggle.py shot_dispenser/*.py tests/*.py
```

Run all unit tests:

```bash
python3 -m unittest discover -s tests
```

Run one test:

```bash
python3 -m unittest tests.test_controller.ControllerTests.test_pvp_right_player_wins_after_green
```

Dry-run mode uses fake hardware and console LCD output, but still reads real numpad events:

```bash
python3 main.py --dry-run --numpad-device /dev/input/eventX
```

If no keyboard/numpad input device is available during a bench test, use explicit terminal control over SSH:

```bash
python3 main.py --terminal-control
```

Terminal control commands:

| Command | Function |
|---|---|
| `hold 1 2` | Run Pump 1 for 2 seconds |
| `1 down` / `1 up` | Start/stop Pump 1 manually |
| `hold random 2` | Run a random pump for 2 seconds |
| `all down` / `all up` | Start/stop all pumps |
| `pvp` | Start PvP |
| `left` / `right` | Left/right PvP player |
| `stop` | Safe stop |
| `quit` | Exit terminal control |

There is no configured lint command.

## Architecture

`main.py` is a small entry point. The implementation lives in `shot_dispenser/`:

| Module | Responsibility |
|---|---|
| `app.py` | CLI parsing, hardware/display/input wiring, startup/shutdown |
| `config.py` | pump GPIO pins, LCD settings, timings, numpad key bindings |
| `controller.py` | pump control, random pump rotation, PvP state machine, safe stop |
| `hardware.py` | GPIO hardware adapter and fake test hardware |
| `display.py` | LCD adapter and console test display |
| `numpad.py` | Linux `evdev` input-device discovery and key mapping |
| `events.py` | Event-publisher boundary for future web server integration |
| `messages.py` | Operator-facing LCD messages |

The older scripts remain for reference and hardware bring-up:

| Script | Purpose |
|---|---|
| `Alles_Dabei.py` | Legacy full version with GPIO buttons and old valve/shared-pump wiring |
| `Pumpe_und_Ventile.py` | Legacy dispenser-only GPIO-button bring-up |
| `ventil_toggle.py` | Single valve/pump wiring sanity check with a different pin map |

## Behavior

### Pump mode

KP1-KP4 run a single pump while held. KP5 chooses a pump from a shuffled pool and runs it while held; all four pumps are used once before any pump repeats. KP6 runs all four pumps while held.

Only one hardware-driving action can run at a time. If a pump, random pump, all-pumps action, or PvP game is active, new actions are rejected and the LCD shows a busy message.

### PvP reaction game

Press KP7 to start.

1. Red turns on for 1 second.
2. Yellow turns on for a random 0.1-4 second delay.
3. Green turns on and players may press.
4. A player press before green is a false start.
5. The first valid player press wins.
6. Timeout is 10 seconds if nobody presses.
7. The winner light stays on until the next operator action or PvP restart.

## Autostart on boot

The current Pi deployment uses `/etc/systemd/system/shotdispenser.service`. The service uses `--pump-active-low` for the active-low relay HAT. The Backspace + KP0 shutdown chord runs the configured Linux poweroff command after stopping the pumps.

```ini
[Unit]
Description=Shot Dispenser
After=bluetooth.target multi-user.target
Wants=bluetooth.target

[Service]
Type=simple
WorkingDirectory=/home/pi/JaegerMASTER-live-test
ExecStart=/usr/bin/python3 /home/pi/JaegerMASTER-live-test/main.py --pump-active-low --shutdown-command /usr/bin/sudo -n /usr/sbin/poweroff
Restart=on-failure
RestartSec=3
User=pi
Group=pi

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable shotdispenser
sudo systemctl restart shotdispenser
```

## Known constraints

- Relay HAT outputs are active-low and configured with `active_high=False`, so the inactive startup state keeps pump relays off. Temporary active-high relay modules require `--pump-active-high`.
- GPIO0, GPIO1, and GPIO11 are avoided because they are reserved or SPI-related.
- GPIO24 is avoided because it is physically damaged on the target unit.
- GPIO2/GPIO3 are reserved for the I2C LCD.
- Future web server calls should be added behind `EventPublisher` after the API endpoints, auth, schemas, timeout/retry rules, and offline behavior are known.
