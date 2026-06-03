from __future__ import annotations

from dataclasses import dataclass, field


# 20x4 main screen art. ASCII only: the HD44780 LCD ROM has no accented or
# musical glyphs and RPLCD raises on unmapped characters. Lines are clipped
# to the display width by the display layer, so trailing padding is harmless.
MAIN_ART: tuple[str, str, str, str] = (
    "* /o/ Jaeger /o/ *",
    "   |  MASTER  |",
    " */ /        / / *",
    "   Bora jogar?",
)


@dataclass(frozen=True)
class OperatorMessages:
    title: str = "JaegerMASTER"
    ready: str = "Pronto!"
    press_button: str = "Use o teclado..."
    busy: str = "Aguarde..."
    stopped: str = "Parado"
    cancelled: str = "Cancelado"
    pump_running: str = "Bomba {} ligada"
    pump_stopped: str = "Bomba {} parada"
    pumps_running: str = "Bombas: {}"
    random_pump: str = "Bomba aleatoria {}"
    all_pumps: str = "Todas as bombas"
    raffle_running: str = "Sorteio: {}"
    pump_limit: str = "Limite 5s atingido"
    release_key: str = "Solte a tecla!"
    booting: str = "Booting..."
    boot_credit_1: str = "Doug Gauzzi Marcone"
    boot_credit_2: str = "Preus Michi A. & G."
    pvp_title: str = "===== Modo PvP ====="
    pvp_get_ready: str = "Preparem-se!"
    pvp_test_title: str = "Testem os botoes:"
    pvp_test_left: str = "7=Esq (VERDE)"
    pvp_test_right: str = "9=Dir (VERMELHO)"
    pvp_test_ok: str = "OK"
    pvp_test_wait: str = "..."
    pvp_prepare: str = "Preparar!"
    pvp_red: str = "VERMELHO"
    pvp_almost: str = "Quase la..."
    pvp_yellow: str = "AMARELO"
    pvp_now: str = ">>> AGORA! <<<"
    pvp_too_slow: str = "Muito lento!"
    pvp_nobody_wins: str = "Ninguem ganhou!"
    pvp_too_early: str = "CEDO DEMAIS!"
    pvp_player: str = "Jogador {}"
    pvp_left_wins: str = "ESQUERDA"
    pvp_right_wins: str = "DIREITA"
    pvp_wins: str = "GANHOU!"
    pvp_reaction_left: str = "Esq: {} ms"
    pvp_reaction_right: str = "Dir: {} ms"
    pvp_no_reaction: str = "--"
    pvp_champion: str = "Campeao 1h: {} ms"
    pvp_waiting: str = "Aguardando..."
    pvp_restart: str = "KP8 = novo jogo"
    input_error: str = "Erro no teclado"
    safe_stop: str = "Block Bombas"
    shutting_down: str = "Desligando"
    restarting: str = "Reiniciando"
    main_art: tuple[str, str, str, str] = field(default_factory=lambda: MAIN_ART)
    credits: tuple[str, ...] = field(
        default_factory=lambda: (
            "Um projeto de amor e odio",
            "Por Doug, Gauzzi, Marcone, Preus, Michi",
            "Andressa e Glauco",
        )
    )


DEFAULT_MESSAGES = OperatorMessages()
