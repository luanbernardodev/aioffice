"""Backtest semanal: junção incremental de dados, regras fixas de revalidação e de grade (sem MT5, sem rede)."""
from datetime import date

import numpy as np
import pandas as pd

from backtest.semanal import dados as D, grade as G, revalidar as R
from backtest.semanal.run import resumo_local


def test_srv_ms_to_utc_winter_and_summer():
    # servidor XM = Nova York + 7h: UTC+2 no inverno, UTC+3 no verão
    winter = pd.Timestamp("2026-01-15 12:00").value // 10**6
    summer = pd.Timestamp("2026-07-15 12:00").value // 10**6
    out = D.srv_ms_to_utc(np.array([winter, summer]))
    assert list(out) == [winter - 2 * 3_600_000, summer - 3 * 3_600_000]


def test_append_ticks_only_after_last_and_in_cents():
    old = {"t": np.array([1, 2, 3], dtype=np.int64), "bid": np.array([100, 101, 102], dtype=np.int32),
           "ask": np.array([110, 111, 112], dtype=np.int32)}
    out = D.append_ticks(old, np.array([2, 3, 4, 5]), np.array([9.0, 9.0, 1.03, 1.04]), np.array([9.0, 9.0, 1.13, 1.14]))
    assert list(out["t"]) == [1, 2, 3, 4, 5] and list(out["bid"][-2:]) == [103, 104] and out["bid"].dtype == np.int32
    assert D.append_ticks(old, np.array([1, 2]), np.array([1.0, 1.0]), np.array([1.0, 1.0])) is old


def test_merge_bars_never_shrinks_and_new_wins():
    old = pd.DataFrame({"time": ["2026-11-01 00:00:00+00:00", "2026-11-01 00:05:00+00:00"], "close": [1.0, 2.0]})
    new = pd.DataFrame({"time": pd.to_datetime(["2026-11-01 00:05", "2026-11-01 00:10"], utc=True), "close": [2.5, 3.0]})
    m = D.merge_bars(old, new)
    assert list(m.close) == [1.0, 2.5, 3.0]


def test_merge_footprint_sums_same_cell():
    ob = pd.DataFrame({"hour": [0, 1], "close": [1, 2]})
    of = pd.DataFrame({"hour": [1], "lvl": [5], "buy": [1.0], "sell": [2.0]})
    nb = pd.DataFrame({"hour": [2], "close": [3]})
    nf = pd.DataFrame({"hour": [1, 2], "lvl": [5, 6], "buy": [1.0, 4.0], "sell": [0.0, 1.0]})
    b, f = D.merge_footprint(ob, of, nb, nf)
    assert list(b.hour) == [0, 1, 2]
    assert f[(f.hour == 1) & (f.lvl == 5)][["buy", "sell"]].values.tolist() == [[2.0, 2.0]]


def test_days_to_fetch_until_yesterday():
    last = int(pd.Timestamp("2026-11-10 23:00", tz="UTC").value // 10**6)
    assert D.days_to_fetch(last, date(2026, 11, 13)) == [date(2026, 11, 11), date(2026, 11, 12)]
    assert D.days_to_fetch(last, date(2026, 11, 11)) == []


def _st(u):
    return R.stats(np.array(u, dtype=float))


def test_classificar_rules():
    hist = _st([1, 1, 1, -1] * 10)                        # 75% de acerto
    assert R.classificar(hist, _st([1] * 5), _st([]), _st([])) == ["amostra pequena (5 trades no forward)"]
    bad = R.classificar(hist, _st([1, -2] * 6), _st([]), _st([]))
    assert any("expectativa negativa" in f for f in bad) and any("acerto caiu" in f for f in bad)
    assert R.classificar(hist, _st([1, 1, 1, -1] * 3), _st([]), _st([])) == ["OK"]
    div = R.classificar(hist, _st([1] * 12), _st([4.0]), _st([-3.0]))
    assert any(f.startswith("DIVERGÊNCIA") for f in div)
    stale = R.classificar(hist, _st([1] * 12), _st([]), _st([-3.0]), cobre_periodo=False)
    assert not any(f.startswith("DIVERGÊNCIA") for f in stale) and any("não cobrem" in f for f in stale)


def test_tabela_splits_history_forward_and_orders_alerts():
    t = pd.to_datetime(["2026-10-01", "2026-11-12", "2026-11-20"] * 6, utc=True)
    good = pd.DataFrame({"t_in": t, "t_out": t, "usd": [1.0, 1.0, 1.0] * 6, "risk_usd": 1.0})
    bad = good.assign(usd=[1.0, -2.0, -2.0] * 6)
    df = R.tabela({"a": ("GOLD", True, good), "b": ("GOLD", True, bad)}, ["a", "b", "c"], {"b": [-1.0]})
    assert list(df.agente) == ["b", "a", "c"]                                  # alerta primeiro
    a = df[df.agente == "a"].iloc[0]
    assert a.hist_n == 6 and a.fwd_n == 12 and a.bt_comp_n == 6
    assert df[df.agente == "c"].situacao.iloc[0] == "sem simulador de backtest"


def test_grade_escolher_uses_is_only():
    base = dict(pf_is=1.5, dd_is=10.0, quebra_is=False, n_oos=20, pf_oos=1.5, wr_oos=0.65, net_oos=5.0, quebra_oos=False,
                tf="H1", sess="all", spec="{}", ex_sl=1, ex_trail=0, ex_act=0, ex_tp=2, ex_mb=48, wr_is=0.6, dd_oos=3.0,
                risco_med=2.0)
    g = pd.DataFrame([{**base, "net_is": 50.0, "wr_oos": 0.40}, {**base, "net_is": 10.0}])   # melhor do IS falha no OOS
    r = G.escolher(g)
    assert r["candidata"] is False and r["IS_US$"] == 50.0                     # o OOS não escolhe
    assert G.escolher(g.iloc[[1]])["candidata"] is True
    assert G.escolher(g.assign(pf_is=1.0))["motivo"] == "nenhuma elegível no IS"


def test_familias_exist_in_grid8():
    from backtest.agentes_v3.grid8_agentes import AGENTS
    assert set(G.FAMILIA.values()) <= set(AGENTS)


def test_resumo_local_says_nothing_changed():
    rev = pd.DataFrame([{"agente": "x", "situacao": "ALERTA: expectativa negativa no forward", "fwd_n": 12,
                         "fwd_liquido": -3.0, "real_comp_n": 2, "real_comp_liquido": -1.0}])
    txt = resumo_local({"ticks": [{"simbolo": "GOLD", "ticks_novos": 10}], "orderflow": {"dias_novos": 2}}, rev, None)
    assert "x: ALERTA" in txt and "Nada foi alterado" in txt and "GOLD +10" in txt
