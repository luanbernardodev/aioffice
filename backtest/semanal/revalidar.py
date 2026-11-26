"""Revalidação semanal dos agentes LIGADOS com os dados atualizados.

Para cada agente: trades do backtest com a configuração ATUAL (mesmos simuladores da análise de capital reverso)
divididos em
  histórico   até o fim dos dados usados na aprovação (FORWARD_DESDE do ativo)
  forward     depois disso: dados que o agente nunca viu (o teste que importa)
  real        trades fechados de verdade no MT5 desde o início da competição, ao lado do backtest no mesmo período

Regras FIXAS (decididas antes de olhar os resultados):
  forward com menos de MIN_N trades           -> "amostra pequena" (nada a concluir)
  forward com expectativa < 0                 -> ALERTA
  acerto forward < acerto histórico - 15 p.p. -> ALERTA
  real x backtest no mesmo período com sinais opostos e diferença >= US$5 -> DIVERGÊNCIA (execução/custos)
Só relata. Nenhuma configuração é alterada.
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

FORWARD_DESDE = {"GOLD": "2026-11-10", "BTCUSD": "2026-11-10", "US500Cash": "2026-11-06"}
COMPETICAO_DESDE = "2026-11-16"
MIN_N = 10
QUEDA_ACERTO = 0.15


def stats(u: np.ndarray) -> Dict[str, Any]:
    u = np.asarray(u, dtype=float)
    if len(u) == 0:
        return {"n": 0, "acerto": None, "pf": None, "liquido": 0.0, "exp": None, "dd": 0.0}
    gl = -u[u < 0].sum()
    eq = np.cumsum(u)
    dd = float((np.maximum.accumulate(np.r_[0.0, eq])[1:] - eq).max())
    return {"n": int(len(u)), "acerto": round(float((u > 0).mean()), 3),
            "pf": round(float(u[u > 0].sum() / gl), 2) if gl > 0 else None,
            "liquido": round(float(u.sum()), 2), "exp": round(float(u.mean()), 3), "dd": round(dd, 2)}


def classificar(hist: Dict[str, Any], fwd: Dict[str, Any], bt_per: Dict[str, Any], real: Dict[str, Any],
                cobre_periodo: bool = True) -> List[str]:
    """cobre_periodo=False: os dados do backtest não chegam ao período da competição -> sem comparação real x backtest."""
    flags = []
    if fwd["n"] < MIN_N:
        flags.append(f"amostra pequena ({fwd['n']} trades no forward)")
    else:
        if fwd["exp"] is not None and fwd["exp"] < 0:
            flags.append("ALERTA: expectativa negativa no forward")
        if hist["acerto"] is not None and fwd["acerto"] is not None and fwd["acerto"] < hist["acerto"] - QUEDA_ACERTO:
            flags.append(f"ALERTA: acerto caiu {hist['acerto']:.0%} -> {fwd['acerto']:.0%}")
    if not cobre_periodo:
        flags.append("dados do backtest não cobrem a competição (sem comparação com o real)")
    elif real["n"] and np.sign(real["liquido"]) != np.sign(bt_per["liquido"]) \
            and abs(real["liquido"] - bt_per["liquido"]) >= 5:
        flags.append(f"DIVERGÊNCIA: real {real['liquido']:+.2f} x backtest {bt_per['liquido']:+.2f} no mesmo período")
    return flags or ["OK"]


def tabela(trades: Dict[str, tuple], ativos: List[str], reais: Dict[str, List[float]],
           fim_dados: Dict[str, pd.Timestamp] | None = None) -> pd.DataFrame:
    """trades: nome -> (símbolo, ligado, DataFrame t_in/t_out/usd/risk_usd). reais: nome -> PnLs reais na competição.
    fim_dados: símbolo -> último dado do backtest (a comparação com o real exige dados até perto de agora)."""
    rows = []
    comp = pd.Timestamp(COMPETICAO_DESDE, tz="UTC")
    for name in ativos:
        if name not in trades:
            rows.append({"agente": name, "situacao": "sem simulador de backtest"})
            continue
        sym, _, tr = trades[name]
        tr = tr.dropna(subset=["usd"]).sort_values("t_out")
        cut = pd.Timestamp(FORWARD_DESDE[sym], tz="UTC")
        h, f = stats(tr[tr.t_in < cut].usd), stats(tr[tr.t_in >= cut].usd)
        per = stats(tr[tr.t_out >= comp].usd)
        real = stats(np.array(reais.get(name, []), dtype=float))
        fim = (fim_dados or {}).get(sym)
        cobre = fim is None or fim >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3)
        r = {"agente": name, "ativo": sym, "situacao": " | ".join(classificar(h, f, per, real, cobre)),
             "fim_dados": fim.strftime("%Y-%m-%d %H:%M") if fim is not None else None,
             "ultimo_trade_bt": tr.t_out.max().strftime("%Y-%m-%d") if len(tr) else None}
        for tag, s in (("hist", h), ("fwd", f), ("bt_comp", per), ("real_comp", real)):
            r.update({f"{tag}_{k}": v for k, v in s.items()})
        rows.append(r)
    order = {"ALERTA": 0, "DIVERG": 1, "amostra": 2, "OK": 3}
    df = pd.DataFrame(rows)
    df["_o"] = df["situacao"].fillna("").map(lambda s: min([v for k, v in order.items() if k in s] or [4]))
    return df.sort_values(["_o", "agente"]).drop(columns="_o").reset_index(drop=True)


def trades_reais(mt5: Any) -> Dict[str, List[float]]:
    """PnL de cada trade fechado no MT5 desde o início da competição, por agente (somente leitura)."""
    from datetime import datetime, timedelta, timezone

    import agents.auditor_mt5 as AUD
    from engine.config import load_config
    cfg = load_config()
    now = datetime.now(timezone.utc)
    raw = mt5.history_deals_get(datetime(2026, 11, 1), now.replace(tzinfo=None) + timedelta(days=1)) or []
    start = datetime.fromisoformat(COMPETICAO_DESDE).replace(tzinfo=timezone.utc)
    out: Dict[str, List[float]] = {}
    for t in AUD.closed_trades(list(raw), start, AUD.agent_names(cfg), cfg["account"].get("server_time", "ny_plus_7")):
        out.setdefault(t["agente"], []).append(t["pnl"])
    return out


def agentes_ligados() -> List[str]:
    import agents.auditor_mt5 as AUD
    from engine.config import load_config
    return sorted(n for n, r in AUD.agent_roster(load_config()).items() if r.get("ligado"))


def fim_dos_dados() -> Dict[str, pd.Timestamp]:
    """Último instante coberto pelos dados de cada ativo (ticks para GOLD/BTC, CSV M5 para o US500)."""
    from backtest import data as bdata
    out: Dict[str, pd.Timestamp] = {}
    for sym in ("GOLD", "BTCUSD"):
        z = np.load(bdata.DATA_DIR / "ticks" / f"{sym}.npz", mmap_mode="r")
        out[sym] = pd.to_datetime(int(z["t"][-1]), unit="ms", utc=True)
    m5 = pd.read_csv(bdata.DATA_DIR / "US500Cash_M5.csv", usecols=["time"]).time.iloc[-1]
    out["US500Cash"] = pd.to_datetime(m5, utc=True)
    return out


def revalidar(mt5: Any) -> pd.DataFrame:
    from backtest.agentes_v3.capital_reverso import collect
    return tabela(collect(), agentes_ligados(), trades_reais(mt5) if mt5 is not None else {}, fim_dos_dados())
