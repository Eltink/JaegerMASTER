from gpiozero import Button, OutputDevice
from signal import pause

# --- Konfiguration ---
BUTTON_VENTIL_PIN = 13   # GPIO13 → Pin 33
BUTTON_PUMPE_PIN  = 19   # GPIO19 → Pin 35
BUTTON_BEIDE_PIN  = 16   # GPIO16 → Pin 36

VENTIL_PIN = 17   # GPIO17 → Pin 11
PUMPE_PIN  = 22   # GPIO22 → Pin 15  ← geändert

# --- Setup ---
btn_ventil = Button(BUTTON_VENTIL_PIN, pull_up=True, bounce_time=0.05)
btn_pumpe  = Button(BUTTON_PUMPE_PIN,  pull_up=True, bounce_time=0.05)
btn_beide  = Button(BUTTON_BEIDE_PIN,  pull_up=True, bounce_time=0.05)

ventil = OutputDevice(VENTIL_PIN, active_high=True, initial_value=False)
pumpe  = OutputDevice(PUMPE_PIN,  active_high=True, initial_value=False)

# --- Logik ---
def toggle_ventil():
    if ventil.is_active:
        ventil.off()
        print("Ventil → GESCHLOSSEN")
    else:
        ventil.on()
        print("Ventil → OFFEN")

def toggle_pumpe():
    if pumpe.is_active:
        pumpe.off()
        print("Pumpe → STOP")
    else:
        pumpe.on()
        print("Pumpe → START")

def toggle_beide():
    if ventil.is_active or pumpe.is_active:
        # Eines läuft → alles stoppen
        
        pumpe.off()
        ventil.off()
        print("Ventil + Pumpe → STOP")
    else:
        # Beides aus → alles starten
        ventil.on()
        pumpe.on()
        print("Ventil + Pumpe → START")

# --- Events ---
btn_ventil.when_pressed = toggle_ventil
btn_pumpe.when_pressed  = toggle_pumpe
btn_beide.when_pressed  = toggle_beide

# --- Start ---
print("Bereit.")
print("  Knopf 1 → Ventil toggle")
print("  Knopf 2 → Pumpe toggle")
print("  Knopf 3 → Ventil + Pumpe zusammen toggle")
pause()
