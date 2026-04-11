from gpiozero import Button, OutputDevice, LED
from signal import pause
from time import sleep
from RPLCD.i2c import CharLCD
import threading
import random

# --- Display ---
LCD_ADRESSE = 0x27
lcd = CharLCD(i2c_expander='PCF8574', address=LCD_ADRESSE,
              port=1, cols=16, rows=2, dotsize=8)

def lcd_print(zeile1="", zeile2=""):
    lcd.clear()
    lcd.cursor_pos = (0, 0); lcd.write_string(zeile1[:16])
    lcd.cursor_pos = (1, 0); lcd.write_string(zeile2[:16])

# --- Konfiguration Dispenser ---
VENTIL_PINS     = [22, 27, 23, 25]  # GPIO → Pin 15, 13, 16, 22
PUMPE_PIN       = 17                 # GPIO17 → Pin 11

BTN_VENTIL_PINS = [26, 19, 13, 6]   # Pin 37, 35, 33, 31
BTN_RANDOM_PIN  = 5                  # Pin 29
BTN_PUMPE_PIN   = 16                 # Pin 36

# --- Konfiguration PvP ---
BTN_PVP_START  = 7    # GPIO7  → Pin 26
BTN_SPIELER1   = 20   # GPIO20 → Pin 38  (links)
BTN_SPIELER2   = 21   # GPIO21 → Pin 40  (rechts)

LED_ROT_PIN    = 12   # GPIO12 → Pin 32  (R)
LED_GELB_PIN   = 18   # GPIO18 → Pin 12  (Y)
LED_GRUEN_PIN  = 4    # GPIO4  → Pin 7   (G)

# --- Setup Dispenser ---
ventile = [OutputDevice(p, active_high=True, initial_value=False) for p in VENTIL_PINS]
pumpe   = OutputDevice(PUMPE_PIN, active_high=True, initial_value=False)

# --- Setup Ampel ---
led_rot   = LED(LED_ROT_PIN)
led_gelb  = LED(LED_GELB_PIN)
led_gruen = LED(LED_GRUEN_PIN)

def ampel_aus():
    led_rot.off()
    led_gelb.off()
    led_gruen.off()

# --- PvP Zustand ---
pvp_aktiv  = False
pvp_bereit = False
pvp_thread = None
pvp_lock   = threading.Lock()

# =====================
#   DISPENSER LOGIK
# =====================

def ventil_sequenz(ventil, stop_event):
    idx = ventile.index(ventil) + 1
    ventil.on()
    lcd_print(f"Ventil {idx} offen", "Warte 1 Sek...")
    print(f"Ventil {idx} → OFFEN")

    for _ in range(10):
        if stop_event.is_set():
            ventil.off()
            lcd_print(f"Ventil {idx} zu", "Abgebrochen")
            print(f"Ventil {idx} → GESCHLOSSEN (abgebrochen)")
            sleep(1)
            lcd_print("Shot Dispenser", "Bereit!")
            return
        sleep(0.1)

    pumpe.on()
    lcd_print(f"Ventil {idx} offen", "Pumpe laeuft...")
    print("Pumpe → START")

    stop_event.wait()

    pumpe.off()
    lcd_print("Pumpe gestoppt", "Ventil schliesst")
    print("Pumpe → STOP")
    sleep(0.5)
    ventil.off()
    print(f"Ventil {idx} → GESCHLOSSEN")
    sleep(1)
    lcd_print("Shot Dispenser", "Bereit!")

def mache_ventil_handler(index):
    stop_event = threading.Event()
    thread = None

    def on_press():
        nonlocal thread
        if pvp_aktiv:
            return
        stop_event.clear()
        thread = threading.Thread(target=ventil_sequenz, args=(ventile[index], stop_event))
        thread.start()

    def on_release():
        stop_event.set()

    return on_press, on_release

_random_pool = []
random_stop_event = threading.Event()

def naechstes_random_ventil():
    global _random_pool
    if not _random_pool:
        _random_pool = list(range(4))
        random.shuffle(_random_pool)
        print(f"Neue Random-Reihenfolge: {[i+1 for i in _random_pool]}")
    return _random_pool.pop()

def random_press():
    if pvp_aktiv:
        return
    idx = naechstes_random_ventil()
    print(f"Random → Ventil {idx+1}")
    random_stop_event.clear()
    threading.Thread(target=ventil_sequenz, args=(ventile[idx], random_stop_event)).start()

def random_release():
    random_stop_event.set()

def pumpe_press():
    if pvp_aktiv:
        return
    pumpe.on()
    lcd_print("Pumpe manuell", "Knopf loslassen!")
    print("Pumpe → START (manuell)")

def pumpe_release():
    pumpe.off()
    lcd_print("Shot Dispenser", "Bereit!")
    print("Pumpe → STOP (manuell)")

# =====================
#     PvP LOGIK
# =====================

def pvp_spiel():
    global pvp_aktiv, pvp_bereit

    ampel_aus()
    lcd_print("=== PvP ===", "Bereit machen!")
    sleep(1)

    # Rot → 1 Sekunde
    led_rot.on()
    lcd_print("=== PvP ===", "ROT...")
    sleep(1)

    # Gelb → zufälliger Delay 0.1–4 Sekunden
    led_rot.off()
    led_gelb.on()
    lcd_print("=== PvP ===", "GELB...")
    delay = random.uniform(0.1, 4)
    sleep(delay)

    # Grün → LOS!
    led_gelb.off()
    led_gruen.on()
    pvp_bereit = True
    lcd_print("=== PvP ===", ">>> JETZT! <<<")
    print("Signal! Drücken!")

    # Timeout 10 Sekunden
    for _ in range(100):
        if not pvp_aktiv:
            break
        sleep(0.1)

    if pvp_aktiv:
        pvp_reset()
        lcd_print("Zu langsam!", "Niemand gewinnt!")
        print("Timeout!")
        sleep(2)
        lcd_print("Shot Dispenser", "Bereit!")

def pvp_gewinner(spieler):
    global pvp_aktiv, pvp_bereit

    with pvp_lock:
        if not pvp_bereit:
            ampel_aus()
            led_gelb.blink(on_time=0.1, off_time=0.1, n=5)
            lcd_print(f"Spieler {spieler}", "ZU FRUEH!")
            print(f"Spieler {spieler} hat zu früh gedrückt!")
            pvp_reset()
            sleep(2)
            lcd_print("Shot Dispenser", "Bereit!")
            return

        if not pvp_aktiv:
            return

        pvp_aktiv  = False
        pvp_bereit = False

    led_gruen.off()

    if spieler == 1:
        led_rot.on()
        lcd_print("SPIELER LINKS", "GEWINNT!")
        print("Spieler 1 (Links) gewinnt!")
    else:
        led_gruen.on()
        lcd_print("SPIELER RECHTS", "GEWINNT!")
        print("Spieler 2 (Rechts) gewinnt!")

    # Licht bleibt an bis PvP Knopf gedrückt wird

def pvp_reset():
    global pvp_aktiv, pvp_bereit
    pvp_aktiv  = False
    pvp_bereit = False
    ampel_aus()

def pvp_start_press():
    global pvp_aktiv, pvp_thread
    if pvp_aktiv:
        return
    pvp_reset()
    pvp_aktiv  = True
    pvp_thread = threading.Thread(target=pvp_spiel)
    pvp_thread.start()

def spieler1_press():
    if not pvp_aktiv and not pvp_bereit:
        return
    threading.Thread(target=pvp_gewinner, args=(1,)).start()

def spieler2_press():
    if not pvp_aktiv and not pvp_bereit:
        return
    threading.Thread(target=pvp_gewinner, args=(2,)).start()

# =====================
#   BUTTONS ERSTELLEN
# =====================

btn_ventile = []
for i, pin in enumerate(BTN_VENTIL_PINS):
    btn = Button(pin, pull_up=True, bounce_time=0.05)
    on_press, on_release = mache_ventil_handler(i)
    btn.when_pressed  = on_press
    btn.when_released = on_release
    btn_ventile.append(btn)

btn_random = Button(BTN_RANDOM_PIN, pull_up=True, bounce_time=0.05)
btn_random.when_pressed  = random_press
btn_random.when_released = random_release

btn_pumpe = Button(BTN_PUMPE_PIN, pull_up=True, bounce_time=0.05)
btn_pumpe.when_pressed  = pumpe_press
btn_pumpe.when_released = pumpe_release

btn_pvp = Button(BTN_PVP_START, pull_up=True, bounce_time=0.05)
btn_s1  = Button(BTN_SPIELER1,  pull_up=True, bounce_time=0.05)
btn_s2  = Button(BTN_SPIELER2,  pull_up=True, bounce_time=0.05)

btn_pvp.when_pressed = pvp_start_press
btn_s1.when_pressed  = spieler1_press
btn_s2.when_pressed  = spieler2_press

# --- Start ---
lcd_print("Shot Dispenser", "Bereit!")
print("Shot Dispenser bereit!")
pause()
