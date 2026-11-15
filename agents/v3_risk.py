"""Proteção de capital dos agentes v3/v4/of_btc (bloco `risco` de config/agente_v3_competicao.yaml).

Com lote mínimo fixo, o único controle de risco é o tamanho do stop e a quantidade de posições. Antes de cada
entrada, `Portfolio.check` recusa se:
  1. o stop desta entrada custa mais que max_risco_trade_pct da equity;
  2. o risco aberto da CONTA (soma, em US$, da distância entrada->stop de TODAS as posições, de qualquer agente)
     somado a esta entrada passa de max_risco_aberto_pct da equity. Posição sem SL conta como risco infinito;
     posição com o stop já além da entrada conta zero;
  3. sem_duplicata: já existe posição (de QUALQUER agente da conta) no mesmo ativo e direção com entrada a menos de
     tolerancia_atr x ATR do sinal (mínimo 2 x spread) — fica só quem abriu primeiro; preço diferente pode abrir;
     (um_por_direcao, se ligado, é mais restrito: 1 posição por ativo/direção entre os agentes deste processo)
  4. a perda do dia (realizado + flutuante da conta, desde 00:00 UTC) já chegou a perda_diaria_pct do saldo inicial.
Grupos em isentos_grupos (ex.: orderflow_btc) não passam pelos itens 1 e 2, e as posições deles não entram no risco
aberto dos demais (orçamentos separados); duplicata e perda diária valem para todos.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from engine.features import server_to_utc

log = logging.getLogger("agents.v3.risk")

DEFAULTS = {"max_risco_trade_pct": 5.0, "max_risco_aberto_pct": 10.0, "um_por_direcao": False, "sem_duplicata": True,
            "tolerancia_atr": 0.1, "perda_diaria_pct": 6.0, "isentos_grupos": []}


def usd_per_price(mt5: Any, symbol: str, volume: float) -> float:
    si = mt5.symbol_info(symbol)
    if si is None or not si.trade_tick_size:
        return float("inf")
    tv = float(getattr(si, "trade_tick_value_loss", 0) or si.trade_tick_value)
    return tv / float(si.trade_tick_size) * float(volume)


def position_risk(mt5: Any, p: Any) -> float:
    """US$ perdidos se o SL atual da posição for atingido (0 se o stop já protege lucro; inf se não há SL)."""
    if not float(p.sl or 0):
        return float("inf")
    side = 1 if int(p.type) == 0 else -1
    dist = (float(p.price_open) - float(p.sl)) * side
    return max(0.0, dist) * usd_per_price(mt5, p.symbol, float(p.volume))


class Portfolio:
    def __init__(self, mt5: Any, cfg: Dict[str, Any], server_time: str = "ny_plus_7",
                 agents_positions: Optional[Callable[[], List[Any]]] = None, clock=None,
                 exempt_magics: Optional[set] = None) -> None:
        self.mt5, self.cfg = mt5, {**DEFAULTS, **(cfg or {})}
        self.exempt_magics = set(exempt_magics or ())
        self.server_time = server_time
        self.agents_positions = agents_positions or (lambda: [])
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def open_risk(self) -> float:
        """Risco aberto da conta, sem as posições dos grupos isentos (orçamento separado)."""
        return sum(position_risk(self.mt5, p) for p in (self.mt5.positions_get() or [])
                   if int(getattr(p, "magic", -1)) not in self.exempt_magics)

    def duplicate(self, symbol: str, side: int, entry: float, tol: float) -> Optional[Any]:
        for p in self.mt5.positions_get() or []:
            if p.symbol == symbol and (1 if int(p.type) == 0 else -1) == side and abs(float(p.price_open) - entry) <= tol:
                return p
        return None

    def day_pnl(self) -> tuple:
        """(perda/ganho do dia em US$ = realizado hoje + flutuante, saldo no início do dia)."""
        now = self.clock()
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        deals = self.mt5.history_deals_get(start - timedelta(days=1), now.replace(tzinfo=None) + timedelta(days=1)) or []
        trade = [d for d in deals if int(d.type) in (0, 1)]
        realized = 0.0
        if trade:
            utc = server_to_utc([int(d.time) for d in trade], self.server_time)
            realized = sum(float(d.profit) + float(d.swap) + float(d.commission)
                           for d, t in zip(trade, utc) if t >= pd.Timestamp(start))
        acc = self.mt5.account_info()
        floating = float(acc.equity) - float(acc.balance)
        return realized + floating, float(acc.balance) - realized

    def check(self, symbol: str, side: int, entry: float, sl: float, volume: float, group: Optional[str] = None,
              a0: float = 0.0, spread: float = 0.0) -> str:
        acc = self.mt5.account_info()
        if acc is None:
            return "conta indisponível"
        equity = float(acc.equity)
        risk = abs(entry - sl) * usd_per_price(self.mt5, symbol, volume)
        if self.cfg["sem_duplicata"]:
            tol = max(float(self.cfg["tolerancia_atr"]) * float(a0 or 0), 2 * float(spread or 0))
            dup = self.duplicate(symbol, side, entry, tol)
            if dup is not None:
                return (f"duplicata: já há {'compra' if side == 1 else 'venda'} em {symbol} a {float(dup.price_open):.2f} "
                        f"(#{dup.ticket}, magic {dup.magic}); esta entraria a {entry:.2f} (tolerância {tol:.2f})")
        exempt = group is not None and group in set(self.cfg.get("isentos_grupos") or [])
        cap = self.cfg["max_risco_trade_pct"] / 100 * equity
        if not exempt and risk > cap:
            return f"risco do trade US${risk:.2f} > {self.cfg['max_risco_trade_pct']:g}% da equity (US${cap:.2f})"
        open_r = self.open_risk()
        cap_all = self.cfg["max_risco_aberto_pct"] / 100 * equity
        if not exempt and open_r + risk > cap_all:
            return (f"risco aberto da conta US${open_r:.2f} + este US${risk:.2f} > "
                    f"{self.cfg['max_risco_aberto_pct']:g}% da equity (US${cap_all:.2f})")
        if self.cfg["um_por_direcao"]:
            for p in self.agents_positions():
                if p.symbol == symbol and (1 if int(p.type) == 0 else -1) == side:
                    return f"já há posição {'compradora' if side == 1 else 'vendedora'} em {symbol} de outro agente"
        pnl, start_bal = self.day_pnl()
        lim = self.cfg["perda_diaria_pct"] / 100 * start_bal
        if start_bal > 0 and pnl <= -lim:
            return f"perda do dia US${pnl:.2f} <= -{self.cfg['perda_diaria_pct']:g}% do saldo inicial (US${lim:.2f})"
        return ""
