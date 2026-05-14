from gpiozero import Button, OutputDevice
from signal import pause
from time import sleep
import threading
import random

# --- Konfiguration ---
VENTIL_PINS  = [22, 27, 23, 25]  # GPIO → Pin 15, 13, 16, 22
PUMPE_PIN    = 17                 # GPIO17 → Pin 11

BTN_VENTIL_PINS = [26, 19, 13, 6]  # Pin 37, 35, 33, 31
BTN_RANDOM_PIN  = 5                # Pin 29
BTN_PUMPE_PIN   = 16                # Pin 36

# --- Setup ---
ventile = [OutputDevice(p, active_high=True, initial_value=False) for p in VENTIL_PINS]
pumpe   = OutputDevice(PUMPE_PIN, active_high=True, initial_value=False)

# --- Zustand ---
aktive_ventil_index = None  # welches Ventil gerade vom Random-Knopf geöffnet wurde

# --- Hilfsfunktion ---
def ventil_sequenz(ventil, stop_event):
    """Öffnet Ventil, wartet 1s, startet Pumpe – solange stop_event nicht gesetzt."""
    ventil.on()
    print(f"Ventil {ventile.index(ventil)+1} → OFFEN")

    # 1 Sekunde warten, aber abbrechen wenn Knopf schon losgelassen
    for _ in range(10):
        if stop_event.is_set():
            ventil.off()
            print(f"Ventil {ventile.index(ventil)+1} → GESCHLOSSEN (abgebrochen)")
            return
        sleep(0.1)
    
    pumpe.on()
    print("Pumpe → START")

    # Warten bis Knopf losgelassen
    stop_event.wait()

    pumpe.off()
    print("Pumpe → STOP")
    sleep(0.5)
    ventil.off()
    print(f"Ventil {ventile.index(ventil)+1} → GESCHLOSSEN")

# --- Button-Handler Factory für Ventile ---
def mache_ventil_handler(index):
    stop_event = threading.Event()
    thread = None

    def on_press():
        nonlocal thread
        stop_event.clear()
        thread = threading.Thread(target=ventil_sequenz, args=(ventile[index], stop_event))
        thread.start()

    def on_release():
        stop_event.set()

    return on_press, on_release

# --- Random Ventil ---
random_stop_event = threading.Event()
random_thread     = None

def random_press():
    global random_thread
    idx = random.randint(0, 3)
    print(f"Random → Ventil {idx+1} gewählt")
    random_stop_event.clear()
    random_thread = threading.Thread(target=ventil_sequenz, args=(ventile[idx], random_stop_event))
    random_thread.start()

def random_release():
    random_stop_event.set()

# --- Pumpe direkt ---
def pumpe_press():
    pumpe.on()
    print("Pumpe → START (manuell)")

def pumpe_release():
    pumpe.off()
    print("Pumpe → STOP (manuell)")

# --- Buttons erstellen ---
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

# --- Start ---
print("Shot Dispenser bereit!")
print("  Knopf 1-4 → Ventil 1-4 (halten)")
print("  Knopf 5   → Random Ventil (halten)")
print("  Knopf 6   → Pumpe direkt (halten)")
pause()
