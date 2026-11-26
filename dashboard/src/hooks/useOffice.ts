'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { supabase } from '@/lib/supabase';
import { AgentStatus, MarketContext, MT5AccountStatus, Trade } from '@/types';

/** Placar da competição gravado pelo sync em system_config.agents_pnl.competicao */
export interface ScoreRow {
  agente: string;
  grupo: 'antigo' | 'novo';
  trades: number;
  pnl: number;
  win_rate_pct: number;
  profit_factor: number | string | null;
  max_dd: number;
}

export interface Competition {
  inicio_utc: string;
  fim_utc?: string | null;
  placar: ScoreRow[];
  total_por_grupo: { antigo: number; novo: number };
}

/** Evento disparado quando uma posição fecha (OPEN -> CLOSED, ou trade novo já CLOSED). */
export interface CloseEvent {
  id: string;
  agentId: string;
  symbol: string;
  side: string;
  profit: number;
  reason?: string | null;
  at: number;
}

/** Ponto do histórico do saldo (tabela account_history, escrita pelo sync). */
export interface BalancePoint {
  ts: string;
  balance: number;
  equity: number | null;
  kind: 'deal' | 'snapshot';
}

const TRADES_SINCE = '2026-11-01T00:00:00Z';
const SNAP_DAYS = 7; // fotos de saldo/equity a cada 10 min: últimos 7 dias (~1000 linhas, o teto da API)

function mergePoints(prev: BalancePoint[], rows: BalancePoint[]): BalancePoint[] {
  const m = new Map(prev.map((p) => [p.ts, p]));
  rows.forEach((r) => m.set(r.ts, { ...r, balance: Number(r.balance), equity: r.equity == null ? null : Number(r.equity) }));
  return [...m.values()].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
}

export function useOffice() {
  const [agents, setAgents] = useState<AgentStatus[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [account, setAccount] = useState<MT5AccountStatus | null>(null);
  const [competition, setCompetition] = useState<Competition | null>(null);
  const [auditor, setAuditor] = useState<MarketContext | null>(null);
  const [events, setEvents] = useState<CloseEvent[]>([]);
  const [balanceHistory, setBalanceHistory] = useState<BalancePoint[]>([]);
  const [connected, setConnected] = useState(false);
  const statusRef = useRef<Record<string, string>>({});

  const emitClose = useCallback((t: Trade) => {
    const ev: CloseEvent = {
      id: `${t.ticket_mt5}`,
      agentId: t.agent_id,
      symbol: t.symbol,
      side: String(t.order_type),
      profit: Number(t.profit_usd) || 0,
      reason: t.exit_reason,
      at: Date.now(),
    };
    setEvents((prev) => [ev, ...prev.filter((e) => e.id !== ev.id)].slice(0, 30));
  }, []);

  const fetchAll = useCallback(async () => {
    const [ag, tr, acc, cfg, mc] = await Promise.all([
      supabase.from('agents_status').select('*').eq('macro_viable', true),
      supabase.from('trades_history').select('*').gte('opened_at', TRADES_SINCE).order('opened_at', { ascending: false }),
      supabase.from('mt5_account_status').select('*').eq('id', 1).limit(1),
      supabase.from('system_config').select('agents_pnl').eq('id', 1).limit(1),
      supabase.from('market_context').select('*').order('created_at', { ascending: false }).limit(1),
    ]);
    if (ag.data) setAgents(ag.data as AgentStatus[]);
    if (tr.data) {
      const list = tr.data as Trade[];
      list.forEach((t) => (statusRef.current[String(t.ticket_mt5)] = String(t.status)));
      setTrades(list);
    }
    if (acc.data?.length) setAccount(acc.data[0] as MT5AccountStatus);
    const comp = (cfg.data?.[0] as { agents_pnl?: { competicao?: Competition } } | undefined)?.agents_pnl?.competicao;
    if (comp) setCompetition(comp);
    if (mc.data?.length) setAuditor(mc.data[0] as MarketContext);
    // histórico do saldo: todos os negócios + fotos recentes (tabela ausente -> gráfico mostra "aguardando")
    const since = new Date(Date.now() - SNAP_DAYS * 86400000).toISOString();
    const [deals, snaps] = await Promise.all([
      supabase.from('account_history').select('*').eq('kind', 'deal').order('ts', { ascending: false }).limit(1000),
      supabase.from('account_history').select('*').eq('kind', 'snapshot').gte('ts', since).order('ts', { ascending: false }).limit(1000),
    ]);
    if ((deals.data && deals.data.length) || (snaps.data && snaps.data.length)) {
      setBalanceHistory(mergePoints([], [...((deals.data as BalancePoint[]) || []), ...((snaps.data as BalancePoint[]) || [])]));
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const ch = supabase
      .channel('office-live')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'agents_status' }, (p) => {
        if (p.eventType === 'DELETE') {
          const old = p.old as AgentStatus;
          setAgents((prev) => prev.filter((a) => a.agent_id !== old.agent_id));
          return;
        }
        const row = p.new as AgentStatus & { macro_viable?: boolean };
        setAgents((prev) => {
          const rest = prev.filter((a) => a.agent_id !== row.agent_id);
          return row.macro_viable === false ? rest : [...rest, row];
        });
      })
      .on('postgres_changes', { event: '*', schema: 'public', table: 'trades_history' }, (p) => {
        if (p.eventType === 'DELETE') {
          const old = p.old as Trade;
          setTrades((prev) => prev.filter((t) => String(t.ticket_mt5) !== String(old.ticket_mt5)));
          return;
        }
        const row = p.new as Trade;
        const key = String(row.ticket_mt5);
        const before = statusRef.current[key];
        statusRef.current[key] = String(row.status);
        // EVENTO: fechou agora (antes estava aberta, ou chegou já fechada)
        if (String(row.status) === 'CLOSED' && before !== 'CLOSED') emitClose(row);
        setTrades((prev) => [row, ...prev.filter((t) => String(t.ticket_mt5) !== key)]);
      })
      .on('postgres_changes', { event: '*', schema: 'public', table: 'mt5_account_status' }, (p) => {
        if (p.new) setAccount(p.new as MT5AccountStatus);
      })
      .on('postgres_changes', { event: '*', schema: 'public', table: 'system_config' }, (p) => {
        const comp = (p.new as { agents_pnl?: { competicao?: Competition } })?.agents_pnl?.competicao;
        if (comp) setCompetition(comp);
      })
      .on('postgres_changes', { event: '*', schema: 'public', table: 'account_history' }, (p) => {
        if (p.new && (p.new as BalancePoint).ts) setBalanceHistory((prev) => mergePoints(prev, [p.new as BalancePoint]));
      })
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'market_context' }, (p) => {
        if (p.new) setAuditor(p.new as MarketContext);
      })
      .subscribe((status) => setConnected(status === 'SUBSCRIBED'));
    return () => {
      supabase.removeChannel(ch);
    };
  }, [fetchAll, emitClose]);

  /** Estatística por agente a partir dos trades reais. */
  const stats = useMemo(() => {
    const out: Record<string, { closed: number; wins: number; pnl: number; open?: Trade; last?: Trade }> = {};
    const asc = [...trades].sort(
      (a, b) => new Date(a.closed_at || a.opened_at).getTime() - new Date(b.closed_at || b.opened_at).getTime(),
    );
    for (const t of asc) {
      const s = (out[t.agent_id] ||= { closed: 0, wins: 0, pnl: 0 });
      if (String(t.status) === 'OPEN') s.open = t;
      else {
        s.closed += 1;
        s.pnl += Number(t.profit_usd) || 0;
        if ((Number(t.profit_usd) || 0) > 0) s.wins += 1;
        s.last = t;
      }
    }
    return out;
  }, [trades]);

  /** Últimos fechamentos (para o feed), mesmo sem evento ao vivo. */
  const recentCloses = useMemo(
    () =>
      trades
        .filter((t) => String(t.status) === 'CLOSED')
        .sort((a, b) => new Date(b.closed_at || 0).getTime() - new Date(a.closed_at || 0).getTime())
        .slice(0, 12),
    [trades],
  );

  /** Demonstração local (?teste-evento): evento fictício só no navegador, nada é gravado no banco. */
  const simulateClose = useCallback((agentId: string, profit: number) => {
    setEvents((prev) => [
      { id: `teste-${Date.now()}`, agentId, symbol: 'TESTE', side: profit >= 0 ? 'BUY' : 'SELL', profit, reason: 'TESTE', at: Date.now() },
      ...prev,
    ].slice(0, 30));
  }, []);

  return {
    agents, trades, account, competition, auditor, events, connected, stats, recentCloses, simulateClose, balanceHistory,
    refetch: fetchAll,
  };
}
