from gpiozero import Button, OutputDevice
from signal import pause

# --- Konfiguration ---
BUTTON_PIN = 13   # GPIO13 → Pin 33
VENTIL_PIN = 17   # GPIO17 → Pin 11

# --- Setup ---
button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)
ventil = OutputDevice(VENTIL_PIN, active_high=True, initial_value=False)

# --- Logik ---
def toggle_ventil():
    if ventil.is_active:
        ventil.off()
        print("Ventil GESCHLOSSEN")
    else:
        ventil.on()
        print("Ventil OFFEN")

# --- Event ---
button.when_pressed = toggle_ventil

# --- Start ---
print("Bereit. Knopf drücken zum Öffnen/Schließen.")
pause()  # Programm läuft, wartet auf Events
