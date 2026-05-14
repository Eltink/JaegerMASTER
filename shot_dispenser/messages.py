from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorMessages:
    title: str = "Mystery Shot Box"
    ready: str = "Pronto!"
    press_button: str = "Use o teclado..."
    busy: str = "Aguarde..."
    stopped: str = "Parado"
    cancelled: str = "Cancelado"
    pump_running: str = "Bomba {} ligada"
    pump_stopped: str = "Bomba {} parada"
    random_pump: str = "Bomba aleatoria {}"
    all_pumps: str = "Todas as bombas"
    release_key: str = "Solte a tecla!"
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
    pvp_left_wins: str = "JOGADOR ESQUERDO"
    pvp_right_wins: str = "JOGADOR DIREITO"
    pvp_wins: str = "GANHOU!"
    pvp_restart: str = "KP7=reiniciar"
    input_error: str = "Erro no teclado"
    safe_stop: str = "Parada segura"


DEFAULT_MESSAGES = OperatorMessages()

