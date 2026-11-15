"""Análise reversa de capital: quanto dinheiro na conta para cada agente (e todos juntos) operar a probabilidade dele
sem quebrar. Configurações ATUAIS dos agentes, lote mínimo, custos reais, SEM a proteção de 8% (que depende do capital).

Trades de cada agente, no simulador mais fiel disponível:
  v4_* e of_btc_*   motor v3 (agents/v3_signals.py + run_bt), mesma grade/corte que os aprovou
  goldnight_v2, goldflip   backtest/flip_tick.py (tick a tick, GOLD 01-11/2026)
  sweep48, rsi20    backtest/agentes_v2/btc_tick.py (tick a tick, BTC 11/2025-11/2026)
  engine A2 / A3    backtest/simulate.run_portfolio (motor do engine, US500 06/2025-11/2026)

Capital adequado = maior de:
  C_dd    = drawdown do pior 1% de 10.000 anos simulados (sorteio dos trades com reposição, na frequência anual
            do agente) / 30%     -> o pior cenário plausível de 1 ano custa no máximo 30% da conta
  C_risco = risco por trade (stop em US$) no percentil 95 / 2%       -> regra clássica de 2% por trade
  margem  = margem de 1 posição no lote mínimo (mt5.order_calc_margin, só leitura)
Expectativa <= 0 -> nenhum capital torna o agente lucrativo. Expectativa > 0 mas negativa no IS ou no OOS -> "frágil".
Carteira: PnL diário alinhado no período comum (02/01-06/11/2026), sorteio em blocos de 7 dias (mantém a correlação
entre agentes), mais o risco aberto simultâneo (percentil 95) / 10% (regra de risco aberto da conta).

  python -m backtest.agentes_v3.capital_reverso
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from agents import v3_signals as V
from agents.v3_agent import load_agents_config
from backtest.agentes_v3.bt import SPECS, run_bt
from backtest.agentes_v3.trailing_test import context
from engine.config import ROOT

OUT = ROOT / "backtest" / "agentes_v3"
SPAN = {"GOLD": ("2026-01-02", "2026-11-10"), "BTCUSD": ("2025-11-01", "2026-11-10"),
        "US500Cash": ("2025-06-10", "2026-11-06")}
COMMON = (pd.Timestamp("2026-01-02", tz="UTC"), pd.Timestamp("2026-11-06", tz="UTC"))
SIMS, DD_TOL, RISK_PCT, OPEN_PCT = 10_000, 0.30, 0.02, 0.10
ATIVOS = {"engine A3", "sweep48", "rsi20", "goldnight_v2"}


def utc(x):
    return pd.to_datetime(x, utc=True)


def collect():
    T = {}
    # v4 e of_btc (motor v3)
    for name, g in load_agents_config().items():
        if not (name.startswith("v4_") or name.startswith("of_btc_")):
            continue
        b, x, s, cut, _ = context(g)
        ex, sym = g["exit"], g["symbol"]
        E, X, S, P, R, N, W = run_bt(*(b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread")), x["atr"],
                                     s, b["sday"].to_numpy(np.int64), float(ex["sl"]), float(ex["trail"]), float(ex["act"]),
                                     float(ex["tp"]), int(g["max_bars"]), 1.0)
        sp = SPECS[sym]
        T[name] = (sym, g["enabled"], pd.DataFrame({
            "t_in": utc(b["time"].to_numpy()[E]), "t_out": utc(b["time"].to_numpy()[X]),
            "usd": P * sp["usd_pp"] + np.where(S == 1, sp["swap"][0], sp["swap"][1]) * N, "risk_usd": R * sp["usd_pp"]}))
    # goldnight_v2 e goldflip (tick a tick)
    from backtest import ticks as TK
    from backtest.flip_tick import Cfg, prepare, simulate
    P = prepare(TK.load("GOLD"))
    for name, c, on in (("goldnight_v2", Cfg(name="goldnight_v2", window="night", trail=3.0, max_risk_usd=10.0), True),
                        ("goldflip", Cfg(name="goldflip", window="day", trail=1.5), False)):
        tr = simulate(P, c)
        T[name] = ("GOLD", on, pd.DataFrame({"t_in": utc(tr.t_in), "t_out": utc(tr.t_out), "usd": tr.usd,
                                             "risk_usd": tr.risk0}))
    del P
    # sweep48 e rsi20 (tick a tick)
    from backtest.agentes_v2.btc_tick import rsi_buy, sweep48
    tk = TK.load("BTCUSD")
    b5 = TK.bars(tk, 5)
    for name, tr in (("sweep48", sweep48(tk, b5)), ("rsi20", rsi_buy(tk, b5, 20, 30, 2.0, 0.5, 0.25))):
        T[name] = ("BTCUSD", True, pd.DataFrame({"t_in": utc(tr.t_in), "t_out": utc(tr.t_out), "usd": tr.usd,
                                                 "risk_usd": tr.risk_usd}))
    del tk, b5
    # engine A2 / A3 (motor do engine)
    import logging
    from backtest import data as bdata
    from backtest.simulate import run_portfolio
    from engine.config import load_config
    logging.getLogger().setLevel(logging.ERROR)
    d, spec = bdata.load("US500Cash")
    for name, agent, on in (("engine A3", "A3_BOS_RETEST", True), ("engine A2", "A2_PULLBACK", False)):
        cfg = load_config(overrides={"symbols": {"GOLD": {"enabled": False}, "BTCUSD": {"enabled": False},
                                                 "US500Cash": {"agents": [agent]}}})
        tr = run_portfolio(cfg, {"US500Cash": d}, {"US500Cash": spec}, spread_mult=1.5)
        T[name] = ("US500Cash", on, pd.DataFrame({
            "t_in": utc([t.opened_at for t in tr]), "t_out": utc([t.closed_at for t in tr]),
            "usd": [t.pnl_usd for t in tr], "risk_usd": [abs(t.entry - t.initial_sl) * t.volume * 1.0 for t in tr]}))
    return T


def margins():
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        out = {}
        for sym in SPECS:
            si, tick = mt5.symbol_info(sym), mt5.symbol_info_tick(sym)
            out[sym] = float(mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, sym, float(si.volume_min), float(tick.ask)) or 0)
        mt5.shutdown()
        return out
    except Exception:  # noqa: BLE001
        return {"GOLD": 20.0, "BTCUSD": 4.0, "US500Cash": 4.0}


def mc_trades(u, n_year, rng):
    k = max(int(round(n_year)), 1)
    s = rng.choice(u, size=(SIMS, k), replace=True)
    eq = np.cumsum(s, axis=1)
    dd = (np.maximum.accumulate(np.concatenate([np.zeros((SIMS, 1)), eq], axis=1), axis=1)[:, 1:] - eq).max(axis=1)
    return np.percentile(dd, 99), float((eq[:, -1] > 0).mean()), float(np.median(eq[:, -1]))


def main():
    rng = np.random.default_rng(11)
    T = collect()
    marg = margins()
    rows = []
    for name, (sym, on, tr) in T.items():
        tr = tr.dropna(subset=["usd"]).sort_values("t_out")
        u, risk = tr.usd.to_numpy(float), tr.risk_usd.to_numpy(float)
        a, b = (utc(x) for x in SPAN[sym])
        years = (b - a).days / 365.25
        cut = a + (b - a) * 0.6
        ui, uo = tr[tr.t_out < cut].usd.to_numpy(), tr[tr.t_out >= cut].usd.to_numpy()
        gl = -u[u < 0].sum()
        exp_all = float(u.mean()) if len(u) else 0.0
        exp_is = float(ui.mean()) if len(ui) else 0.0
        exp_oos = float(uo.mean()) if len(uo) else 0.0
        if exp_all <= 0:
            classe = "negativo"
        elif exp_is > 0 and exp_oos > 0:
            classe = "lucrativo"
        else:
            classe = "frágil"
        r = {"agente": name, "ativo": sym, "status": "ligado" if (on or name in ATIVOS) else "desligado", "classe": classe,
             "trades": len(u), "trades_ano": round(len(u) / years, 1), "acerto": round(float((u > 0).mean()), 3) if len(u) else 0,
             "PF": round(float(u[u > 0].sum() / gl), 2) if gl > 0 else 99.0, "exp_trade": round(exp_all, 3),
             "exp_IS": round(exp_is, 3), "exp_OOS": round(exp_oos, 3), "lucro_ano": round(exp_all * len(u) / years, 1),
             "risco_p95": round(float(np.percentile(risk, 95)), 2) if len(risk) else 0.0, "margem": round(marg[sym], 2)}
        if classe != "negativo" and len(u) >= 10:
            dd99, p_lucro, med = mc_trades(u, len(u) / years, rng)
            c_dd, c_r = dd99 / DD_TOL, r["risco_p95"] / RISK_PCT
            r.update({"DD99_1ano": round(dd99, 1), "P_lucro_1ano": round(p_lucro, 3), "C_dd": round(c_dd), "C_risco": round(c_r),
                      "capital_adequado": round(max(c_dd, c_r, r["margem"])),
                      "retorno_ano_%": round(100 * r["lucro_ano"] / max(c_dd, c_r, r["margem"]), 1)})
        rows.append(r)
    df = pd.DataFrame(rows).sort_values(["classe", "capital_adequado"], na_position="last")
    df.to_csv(OUT / "capital_reverso.csv", index=False)

    # carteira (período comum, PnL diário alinhado, sorteio em blocos)
    days = pd.date_range(COMMON[0], COMMON[1], freq="D")
    port = {}
    for label, members in (("lucrativos", df[df.classe == "lucrativo"].agente.tolist()),
                           ("lucrativos + frágeis", df[df.classe != "negativo"].agente.tolist()),
                           ("ligados e lucrativos", df[(df.classe == "lucrativo") & (df.status == "ligado")].agente.tolist())):
        if not members:
            continue
        daily = pd.DataFrame(0.0, index=days, columns=members)
        events = []
        for m in members:
            tr = T[m][2]
            tr = tr[(tr.t_out >= COMMON[0]) & (tr.t_out <= COMMON[1])]
            s = tr.groupby(tr.t_out.dt.floor("D")).usd.sum()
            daily.loc[daily.index.intersection(s.index), m] = s[s.index.isin(daily.index)]
            events += [(t, r_) for t, r_ in zip(tr.t_in, tr.risk_usd)] + [(t, -r_) for t, r_ in zip(tr.t_out, tr.risk_usd)]
        tot = daily.sum(axis=1).to_numpy()
        ev = sorted(events, key=lambda e: e[0])
        conc = np.cumsum([e[1] for e in ev]) if ev else np.zeros(1)
        blocks = len(tot) // 7
        sims = []
        for _ in range(SIMS):
            idx = rng.integers(0, len(tot) - 7, size=53)
            path = np.concatenate([tot[i:i + 7] for i in idx])[:365]
            eq = np.cumsum(path)
            sims.append(((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max(), eq[-1]))
        sims = np.array(sims)
        dd99 = float(np.percentile(sims[:, 0], 99))
        c_open = float(np.percentile(conc, 95)) / OPEN_PCT
        c_risk = float(df[df.agente.isin(members)].risco_p95.max()) / RISK_PCT
        c_marg = float(df[df.agente.isin(members)].margem.sum())
        port[label] = {"agentes": len(members), "lucro_ano_estimado": round(float(tot.sum()) * 365 / len(tot), 1),
                       "DD99_1ano": round(dd99, 1), "P_lucro_1ano": round(float((sims[:, 1] > 0).mean()), 3),
                       "risco_aberto_p95": round(float(np.percentile(conc, 95)), 1), "C_dd": round(dd99 / DD_TOL),
                       "C_risco_aberto": round(c_open), "C_risco_trade": round(c_risk), "margem_todos": round(c_marg),
                       "capital_adequado": round(max(dd99 / DD_TOL, c_open, c_risk, c_marg)), "membros": members}
    with open(OUT / "capital_reverso_carteira.json", "w", encoding="utf-8") as fh:
        json.dump(port, fh, ensure_ascii=False, indent=2)
    with pd.option_context("display.width", 400, "display.max_rows", 100):
        print(df.to_string(index=False))
    for k, v in port.items():
        print(f"\nCARTEIRA {k}: " + json.dumps({kk: vv for kk, vv in v.items() if kk != "membros"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
