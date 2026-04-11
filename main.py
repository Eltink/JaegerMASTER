from gpiozero import Button, OutputDevice, LED
from signal import pause
from time import sleep
from RPLCD.i2c import CharLCD
import atexit
import threading
import random

# =====================
#   DISPLAY
# =====================

LCD_ADDRESS = 0x27
lcd = CharLCD(i2c_expander='PCF8574', address=LCD_ADDRESS,
              port=1, cols=20, rows=4, dotsize=8)

MSG = {
    "title":           "Shot Dispenser",
    "ready":           "Pronto!",
    "press_button":    "Aperte o botao...",
    "valve_open":      "Valvula {} aberta",
    "valve_closed":    "Valvula {} fechada",
    "valve_closing":   "Valvula fechando...",
    "wait_1s":         "Aguarde 1 segundo..",
    "pump_running":    "Bomba ligada...",
    "pump_stopped":    "Bomba parada",
    "pump_manual":     "Bomba manual",
    "release_button":  "Solte o botao!",
    "cancelled":       "Cancelado",
    "pvp_title":       "=== Modo PvP ===",
    "pvp_get_ready":   "Preparem-se!",
    "pvp_prepare":     "Preparar!",
    "pvp_red":         "VERMELHO",
    "pvp_almost":      "Quase la...",
    "pvp_yellow":      "AMARELO",
    "pvp_now":         ">>> AGORA! <<<",
    "pvp_too_slow":    "Muito lento!",
    "pvp_nobody_wins": "Ninguem ganhou!",
    "pvp_too_early":   "CEDO DEMAIS!",
    "pvp_player":      "Jogador {}",
    "pvp_left_wins":   "JOGADOR ESQUERDO",
    "pvp_right_wins":  "JOGADOR DIREITO",
    "pvp_wins":        "GANHOU!",
    "pvp_restart":     "Botao=reiniciar",
}


def lcd_print(line1="", line2="", line3="", line4=""):
    lcd.clear()
    lcd.cursor_pos = (0, 0); lcd.write_string(line1[:20])
    lcd.cursor_pos = (1, 0); lcd.write_string(line2[:20])
    lcd.cursor_pos = (2, 0); lcd.write_string(line3[:20])
    lcd.cursor_pos = (3, 0); lcd.write_string(line4[:20])


def lcd_ready():
    lcd_print(MSG["title"], MSG["ready"], "", MSG["press_button"])


# =====================
#   GPIO CONFIGURATION
# =====================

VALVE_PINS      = [22, 27, 23, 25]   # GPIO -> Pin 15, 13, 16, 22
PUMP_PIN        = 17                 # GPIO17 -> Pin 11

BTN_VALVE_PINS  = [26, 19, 13, 6]    # Pin 37, 35, 33, 31
BTN_RANDOM_PIN  = 5                  # Pin 29
BTN_PUMP_PIN    = 16                 # Pin 36

BTN_PVP_START   = 7                  # GPIO7  -> Pin 26
BTN_PLAYER1     = 20                 # GPIO20 -> Pin 38 (left)
BTN_PLAYER2     = 21                 # GPIO21 -> Pin 40 (right)

LED_RED_PIN     = 12                 # GPIO12 -> Pin 32
LED_YELLOW_PIN  = 18                 # GPIO18 -> Pin 12
LED_GREEN_PIN   = 4                  # GPIO4  -> Pin 7

# =====================
#   GPIO SETUP
# =====================

valves = [OutputDevice(p, active_high=True, initial_value=False) for p in VALVE_PINS]
pump   = OutputDevice(PUMP_PIN, active_high=True, initial_value=False)

led_red    = LED(LED_RED_PIN)
led_yellow = LED(LED_YELLOW_PIN)
led_green  = LED(LED_GREEN_PIN)


def traffic_light_off():
    led_red.off()
    led_yellow.off()
    led_green.off()


# =====================
#   CLEANUP
# =====================

def cleanup():
    pump.off()
    for v in valves:
        v.off()
    traffic_light_off()
    lcd.clear()

atexit.register(cleanup)

# =====================
#   DISPENSER LOGIC
# =====================

pvp_active = False
pvp_ready = False
pvp_lock = threading.Lock()
pvp_done = threading.Event()


def valve_sequence(valve, stop_event):
    idx = valves.index(valve) + 1
    valve.on()
    lcd_print(MSG["title"], MSG["valve_open"].format(idx), MSG["wait_1s"], "")
    print(f"Valve {idx} -> OPEN")

    for _ in range(10):
        if stop_event.is_set():
            valve.off()
            lcd_print(MSG["title"], MSG["valve_closed"].format(idx), MSG["cancelled"], "")
            print(f"Valve {idx} -> CLOSED (cancelled)")
            sleep(1)
            lcd_ready()
            return
        sleep(0.1)

    pump.on()
    lcd_print(MSG["title"], MSG["valve_open"].format(idx), MSG["pump_running"], MSG["release_button"])
    print("Pump -> START")

    stop_event.wait()

    pump.off()
    lcd_print(MSG["title"], MSG["valve_open"].format(idx), MSG["pump_stopped"], MSG["valve_closing"])
    print("Pump -> STOP")
    sleep(0.5)
    valve.off()
    print(f"Valve {idx} -> CLOSED")
    sleep(1)
    lcd_ready()


def make_valve_handler(index):
    stop_event = threading.Event()

    def on_press():
        if pvp_active:
            return
        stop_event.clear()
        threading.Thread(target=valve_sequence, args=(valves[index], stop_event)).start()

    def on_release():
        stop_event.set()

    return on_press, on_release


_random_pool = []
random_stop_event = threading.Event()


def next_random_valve():
    global _random_pool
    if not _random_pool:
        _random_pool = list(range(len(valves)))
        random.shuffle(_random_pool)
        print(f"New random order: {[i + 1 for i in _random_pool]}")
    return _random_pool.pop()


def random_press():
    if pvp_active:
        return
    idx = next_random_valve()
    random_stop_event.clear()
    threading.Thread(target=valve_sequence, args=(valves[idx], random_stop_event)).start()


def random_release():
    random_stop_event.set()


def pump_press():
    if pvp_active:
        return
    pump.on()
    lcd_print(MSG["title"], MSG["pump_manual"], MSG["pump_running"], MSG["release_button"])
    print("Pump -> START (manual)")


def pump_release():
    pump.off()
    lcd_ready()
    print("Pump -> STOP (manual)")


# =====================
#   PvP LOGIC
# =====================

def pvp_game():
    global pvp_active, pvp_ready

    traffic_light_off()
    lcd_print(MSG["pvp_title"], MSG["pvp_get_ready"], "", "")

    led_red.on()
    lcd_print(MSG["pvp_title"], MSG["pvp_prepare"].center(20), MSG["pvp_red"].center(20), "")
    if pvp_done.wait(timeout=1):
        return

    led_red.off()
    led_yellow.on()
    lcd_print(MSG["pvp_title"], MSG["pvp_almost"].center(20), MSG["pvp_yellow"].center(20), "")
    if pvp_done.wait(timeout=random.uniform(0.1, 4)):
        return

    led_yellow.off()
    led_green.on()
    with pvp_lock:
        pvp_ready = True
    lcd_print(MSG["pvp_title"], "", MSG["pvp_now"].center(20), "")
    print("Signal! Press!")

    pvp_done.wait(timeout=10)

    with pvp_lock:
        timed_out = pvp_active
        if timed_out:
            pvp_active = False
            pvp_ready = False

    if timed_out:
        traffic_light_off()
        lcd_print(MSG["pvp_title"], MSG["pvp_too_slow"].center(20), MSG["pvp_nobody_wins"].center(20), "")
        print("Timeout!")
        sleep(2)
        lcd_ready()


def pvp_winner(player):
    global pvp_active, pvp_ready

    with pvp_lock:
        if not pvp_active:
            return
        if not pvp_ready:
            pvp_active = False
            pvp_ready = False
            pvp_done.set()
            too_early = True
        else:
            pvp_active = False
            pvp_ready = False
            pvp_done.set()
            too_early = False

    if too_early:
        traffic_light_off()
        lcd_print(
            MSG["pvp_title"],
            MSG["pvp_player"].format(player).center(20),
            MSG["pvp_too_early"].center(20), "",
        )
        print(f"Player {player} pressed too early!")
        led_yellow.blink(on_time=0.1, off_time=0.1, n=5, background=False)
        sleep(1)
        lcd_ready()
        return

    led_green.off()
    if player == 1:
        led_red.on()
        lcd_print(MSG["pvp_title"], MSG["pvp_left_wins"].center(20), MSG["pvp_wins"].center(20), MSG["pvp_restart"])
        print("Player 1 (Left) wins!")
    else:
        led_green.on()
        lcd_print(MSG["pvp_title"], MSG["pvp_right_wins"].center(20), MSG["pvp_wins"].center(20), MSG["pvp_restart"])
        print("Player 2 (Right) wins!")


def pvp_start_press():
    global pvp_active, pvp_ready

    with pvp_lock:
        if pvp_active:
            return
        traffic_light_off()
        pvp_active = True
        pvp_ready = False
        pvp_done.clear()

    threading.Thread(target=pvp_game).start()


def player_press(player):
    if not pvp_active:
        return
    threading.Thread(target=pvp_winner, args=(player,)).start()


# =====================
#   BUTTON SETUP
# =====================

btn_valves = []
for i, pin in enumerate(BTN_VALVE_PINS):
    btn = Button(pin, pull_up=True, bounce_time=0.05)
    on_press, on_release = make_valve_handler(i)
    btn.when_pressed  = on_press
    btn.when_released = on_release
    btn_valves.append(btn)

btn_random = Button(BTN_RANDOM_PIN, pull_up=True, bounce_time=0.05)
btn_random.when_pressed  = random_press
btn_random.when_released = random_release

btn_pump = Button(BTN_PUMP_PIN, pull_up=True, bounce_time=0.05)
btn_pump.when_pressed  = pump_press
btn_pump.when_released = pump_release

btn_pvp = Button(BTN_PVP_START, pull_up=True, bounce_time=0.05)
btn_p1  = Button(BTN_PLAYER1,   pull_up=True, bounce_time=0.05)
btn_p2  = Button(BTN_PLAYER2,   pull_up=True, bounce_time=0.05)

btn_pvp.when_pressed = pvp_start_press
btn_p1.when_pressed  = lambda: player_press(1)
btn_p2.when_pressed  = lambda: player_press(2)

# =====================
#   START
# =====================

lcd_ready()
print("Shot Dispenser ready!")
pause()