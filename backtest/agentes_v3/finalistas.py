"""Análise detalhada dos 5 finalistas da grade v3 (mesmo motor, custo real).
  python -m backtest.agentes_v3.finalistas
"""
import numpy as np
import pandas as pd

from agents import v3_signals as V
from backtest.agentes_v3.bt import TF_MIN, bars, run_bt, summarize, trades_usd

MAX_BARS = 96
FINALISTAS = {
    "v3_gold_chan_m15": ("GOLD", "M15", dict(family="CHAN", k=2.0, filter="none", session="night"),
                         dict(sl=1.5, trail=0, act=0, tp=0)),
    "v3_gold_ema_m15": ("GOLD", "M15", dict(family="EMAX", f=9, s=21, session="night"),
                        dict(sl=1.5, trail=0, act=0, tp=0)),
    "v3_us500_sweep_h1": ("US500Cash", "H1", dict(family="SWEEP", n=48, filter="none", session="all"),
                          dict(sl=3.0, trail=0, act=0, tp=3.0)),
    "v3_us500_st_h1": ("US500Cash", "H1", dict(family="ST", p=10, m=3.0, filter="ema200", session="ny"),
                       dict(sl=1.5, trail=1.5, act=1.0, tp=0)),
    "v3_btc_rsi_h1": ("BTCUSD", "H1", dict(family="RSIX", x=25, side="both", filter="none", session="all"),
                      dict(sl=1.5, trail=3.0, act=0, tp=0)),
}


def trades(sym, tf, spec, ex, sp_mult=1.0):
    b = bars(sym, tf)
    x = V.indicators(b)
    sig = np.where(V.session_mask(b["time"], spec.get("session", "all"), TF_MIN[tf]), V.signal(x, spec), 0)
    res = run_bt(*(b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread")), x["atr"],
                 sig.astype(np.int64), b["sday"].to_numpy(np.int64), ex["sl"], ex["trail"], ex["act"], ex["tp"],
                 MAX_BARS, sp_mult)
    return b, trades_usd(sym, b, res)


def halt_path(u, limit=40.0):
    """Se o agente começasse em cada trade, em quantos % das partidas a perda acumulada bateria -limit?"""
    hits = 0
    for s in range(len(u)):
        eq = np.cumsum(u[s:])
        hits += bool((eq <= -limit).any())
    return hits / max(len(u), 1)


def main():
    for name, (sym, tf, spec, ex) in FINALISTAS.items():
        b, tr = trades(sym, tf, spec, ex)
        u = tr.usd.to_numpy()
        f = summarize(u)
        lo, sh = tr[tr.side == 1].usd, tr[tr.side == -1].usd
        top = np.sort(u)[::-1]
        streak = max((len(list(g)) for k, g in __import__("itertools").groupby(u < 0) if k), default=0)
        print(f"\n=== {name}  {sym} {tf} {spec} {ex}")
        print(f"  {b.time.iloc[0]:%Y-%m-%d} -> {b.time.iloc[-1]:%Y-%m-%d} | n={f['n']} PF={f['pf']:.2f} net=${f['net']:+.1f} "
              f"DD=${f['dd']:.1f} acerto={100 * f['wr']:.0f}% | risco mediano ${tr.risk_usd.median():.2f} | "
              f"pior ${u.min():+.2f} | maior ${u.max():+.2f}")
        print(f"  compras n={len(lo)} ${lo.sum():+.1f} | vendas n={len(sh)} ${sh.sum():+.1f} | sem os 3 maiores ${u.sum() - top[:3].sum():+.1f}"
              f" | perdas seguidas máx {streak} | saídas {tr.groupby('why').usd.agg(['size', 'sum']).round(1).to_dict('index')}")
        m = tr.groupby(tr.t_out.dt.strftime("%y-%m")).usd.sum()
        print("  por mês:", " ".join(f"{k}:{v:+.0f}" for k, v in m.items()), f"| meses +: {(m > 0).sum()}/{len(m)}")
        print(f"  partidas que batem -US$40: {100 * halt_path(u):.0f}% | spread x2: PF {summarize(trades(sym, tf, spec, ex, 2.0)[1].usd.to_numpy())['pf']:.2f}")


if __name__ == "__main__":
    main()
