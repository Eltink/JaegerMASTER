from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorMessages:
    # Used on action screens (pump running, PvP countdown, etc.) — 20 chars max
    title: str = "    JaegerMASTER    "
    ready: str = "Pronto!"
    press_button: str = "Use o teclado..."
    busy: str = "Aguarde..."
    stopped: str = "Parado"
    cancelled: str = "Cancelado"
    pump_running: str = "Bomba {} ligada"
    pump_stopped: str = "Bomba {} parada"
    pump_multi: str = "Bombas: {}"
    random_pump: str = "Bomba aleatoria {}"
    all_pumps: str = "Todas as bombas"
    lottery_msg: str = "Sorteio! {} bombas"
    release_key: str = "Solte a tecla!"
    # PvP
    pvp_title: str = "===== Modo PvP ====="
    pvp_get_ready: str = "Preparem-se!"
    pvp_prepare: str = "Preparar!"
    pvp_red: str = "VERMELHO"
    pvp_almost: str = "Quase la..."
    pvp_yellow: str = "AMARELO"
    pvp_now: str = ">>> AGORA! <<<"
    pvp_too_slow: str = "Muito lento!"
    pvp_nobody_wins: str = "Ninguem ganhou!"
    pvp_too_early: str = "CEDO DEMAIS!"
    pvp_player: str = "Jogador {}"
    pvp_left_wins: str = "ESQUERDO"
    pvp_right_wins: str = "DIREITO"
    pvp_wins: str = "GANHOU!"
    pvp_restart: str = "KP8=nova rodada"
    pvp_left_button: str = "KP7=Esquerdo(Verde)"
    pvp_right_button: str = "KP9=Direito(Verm.) "
    pvp_p1_ready: str = "J.Esq: OK!"
    pvp_p2_ready: str = "J.Dir: OK!"
    pvp_waiting_p1: str = "Aguardando J.Esq..."
    pvp_waiting_p2: str = "Aguardando J.Dir..."
    pvp_press_button: str = "Pressione seu botao"
    pvp_champion: str = "Campiao 1h: {}ms"
    # Operator
    input_error: str = "Erro no teclado"
    safe_stop: str = "Block Bombas"
    shutdown_message: str = "   Desligando...    "
    # Main ready screen — full 4-line ASCII art (each exactly 20 chars)
    main_line1: str = "# \\o/ Jaeger  \\o/ * "
    main_line2: str = "   |  MASTER  |     "
    main_line3: str = " */ \\        / \\  ~ "
    main_line4: str = "   Bora jogar?      "
    # Boot scrolling credits
    boot_credits: str = (
        "  Um projeto de amor e odio  "
        "Por Doug, Gauzzi, Marcone, Preus, Michi, Andressa e Glauco   "
    )


DEFAULT_MESSAGES = OperatorMessages()
