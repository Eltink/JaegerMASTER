# 🥃 Shot Dispenser

A Raspberry Pi 4 powered shot dispenser with PvP reaction game mode, controlled via solenoid valves, a pump, buttons, a traffic light LED and a 16x2 LCD display.

---

## Hardware

| Component | Details |
|---|---|
| Microcontroller | Raspberry Pi 4 Model B (BCM2711, Quad-Core ARM Cortex-A72, 64-bit) |
| Valves | 4x solenoid valves via relay module |
| Pump | 1x pump via relay module |
| Display | 16x2 LCD with I2C adapter (PCF8574) |
| LEDs | Traffic light (Red / Yellow / Green) with shared GND |
| Buttons | 9x momentary push buttons (GPIO → Button → GND) |

> **Note:** All buttons use the Pi's internal pull-up resistors. No external resistors needed.

---

## Wiring

### Relay Outputs

| Pin | GPIO | Function |
|---|---|---|
| 15 | GPIO22 | Valve 1 |
| 13 | GPIO27 | Valve 2 |
| 16 | GPIO23 | Valve 3 |
| 22 | GPIO25 | Valve 4 |
| 11 | GPIO17 | Pump |

### Buttons (all wired GPIO → Button → GND)

| Pin | GPIO | Function |
|---|---|---|
| 37 | GPIO26 | Valve 1 |
| 35 | GPIO19 | Valve 2 |
| 33 | GPIO13 | Valve 3 |
| 31 | GPIO6 | Valve 4 |
| 29 | GPIO5 | Random Valve |
| 36 | GPIO16 | Pump Manual |
| 26 | GPIO7 | PvP Start |
| 38 | GPIO20 | Player 1 (Left) |
| 40 | GPIO21 | Player 2 (Right) |

### Traffic Light

| Pin | GPIO | Function |
|---|---|---|
| 32 | GPIO12 | Red |
| 12 | GPIO18 | Yellow |
| 7 | GPIO4 | Green |

### Display (I2C)

| Pin | Function |
|---|---|
| Pin 3 (GPIO2) | SDA |
| Pin 5 (GPIO3) | SCL |
| Pin 4 | 5V |
| Pin 6 | GND |

---

## Software

### Requirements

```bash
sudo apt update
sudo apt install python3-gpiozero python3-smbus i2c-tools -y
pip install RPLCD --break-system-packages
```

### Enable I2C

```bash
sudo raspi-config
# Interface Options → I2C → Enable
sudo reboot
```

### Verify Display Address

```bash
i2cdetect -y 1
# Should show 27 or 3f
```

Update `LCD_ADDRESS` in the code accordingly (`0x27` or `0x3F`).

### Run

```bash
python3 Alles_Dabei.py
```

### Autostart on Boot (optional)

```bash
sudo nano /etc/systemd/system/shotdispenser.service
```

```ini
[Unit]
Description=Shot Dispenser
After=multi-user.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/JaegerMASTER/Alles_Dabei.py
WorkingDirectory=/home/pi/JaegerMASTER
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable shotdispenser
sudo systemctl start shotdispenser
```

---

## Functionality

### Dispenser Mode

- **Valve buttons (hold):** Valve opens → 1 second delay → pump starts → release button → pump stops immediately → valve closes after 0.5s
- **Random button (hold):** Picks a valve in shuffled order — all 4 valves are used before any repeats
- **Pump button (hold):** Manual pump control
- All dispenser buttons are disabled during PvP mode

### PvP Reaction Game Mode

Press the **PvP Start button** to activate.

**Sequence:**
```
🔴 Red ON  (1 second)
        ↓
🟡 Yellow ON  (random 0.1 – 4 seconds, anti-cheat)
        ↓
🟢 Green ON  → PRESS NOW!
        ↓
Too early? → Disqualified (yellow blinks)
First to press wins!
        ↓
Left player wins  → 🔴 Red stays on
Right player wins → 🟢 Green stays on
        ↓
Winner light stays on until PvP button is pressed again
10 second timeout if nobody presses
```

---

## Known Constraints

- `active_high=True` is set for relays — if your relay module is **active LOW** (LED slightly glows at rest), change to `active_high=False`
- **GPIO0, GPIO1, GPIO11** are avoided (reserved / SPI)
- **GPIO24 (Pin 18)** avoided — physically damaged on our unit
- If using `dtoverlay=gpio-shutdown`, move it away from GPIO2/3 to avoid I2C conflict — e.g. `gpio_pin=8` (Pin 24)
- Display contrast is adjusted via the **blue potentiometer** on the I2C adapter — no software control possible

---

## Display Messages

All LCD messages are defined in the `MSG` dictionary at the top of the script for easy customization.

```python
MSG = {
    "title":   "Shot Dispenser",
    "ready":   "Bereit!",
    ...
}
```
