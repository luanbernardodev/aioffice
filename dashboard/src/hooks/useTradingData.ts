'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { supabase } from '@/lib/supabase';
import { Trade, MT5AccountStatus, AgentPerformanceItem, AgentPerformanceMap, CumulativeEquityPoint } from '@/types';

// Agentes de mesa operacionais padrão
export const STANDARD_OPS_AGENTS = ['ops_alpha', 'ops_delta', 'ops_beta', 'ops_epsilon', 'ops_gamma'];

/**
 * Converte um agent_id para nome amigável para séries de gráfico
 * Ex: 'ops_alpha' -> 'Alpha', 'ops_delta' -> 'Delta'
 */
export function getAgentFriendlyName(agentId: string): string {
  const clean = agentId.replace(/^ops_/, '').replace(/_v\d+$/i, '');
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

/**
 * Formata um valor numérico de PnL para texto com cor e sinal
 */
export function formatPnLValue(value: number): {
  formatted: string;
  isPositive: boolean;
  colorClass: string;
  dotColorClass: string;
} {
  const rounded = Math.round((Number(value) || 0) * 100) / 100;
  const isPositive = rounded > 0;
  const isNegative = rounded < 0;
  const sign = isPositive ? '+' : isNegative ? '-' : '';
  const absVal = Math.abs(rounded).toFixed(2);
  const formatted = `${sign}$${absVal}`;

  return {
    formatted,
    isPositive,
    colorClass: isPositive ? 'text-emerald-400' : isNegative ? 'text-rose-400' : 'text-slate-400',
    dotColorClass: isPositive ? 'bg-emerald-400' : isNegative ? 'bg-rose-500' : 'bg-slate-500',
  };
}

/**
 * Constrói a linha temporal para o Recharts a partir de trades fechadas.
 * Cada ordem fechada avança a linha do tempo.
 * Se vazio, retorna array vazio para evitar linhas retas falsas.
 */
export function buildPerformanceTimeline(
  trades: Trade[],
  targetAgentIds: string[] = STANDARD_OPS_AGENTS
): CumulativeEquityPoint[] {
  if (!trades || !Array.isArray(trades)) return [];

  // Filtra estritamente operações encerradas (CLOSED) com datas válidas
  const closedTrades = trades
    .filter((t) => String(t.status || '').trim().toUpperCase() === 'CLOSED')
    .sort((a, b) => {
      const timeA = new Date(a.closed_at || a.opened_at || 0).getTime();
      const timeB = new Date(b.closed_at || b.opened_at || 0).getTime();
      return timeA - timeB;
    });

  if (closedTrades.length === 0) {
    return [];
  }

  // Identifica todos os IDs de agentes relevantes (padrões + existentes nas ordens)
  const agentIdsSet = new Set<string>(targetAgentIds);
  closedTrades.forEach((t) => {
    if (t.agent_id) agentIdsSet.add(t.agent_id);
  });
  const allAgentIds = Array.from(agentIdsSet);

  const cumMap: Record<string, number> = {};
  allAgentIds.forEach((id) => {
    cumMap[id] = 0;
  });

  let runningTotal = 0;
  const points: CumulativeEquityPoint[] = [];

  // Ponto zero inicial: 1 minuto antes da primeira operação para traçar o ponto de partida
  const firstTradeTime = new Date(closedTrades[0].closed_at || closedTrades[0].opened_at || Date.now()).getTime();
  const initialTimeStr = new Date(firstTradeTime - 60000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const initialPoint: CumulativeEquityPoint = {
    time: initialTimeStr,
    timestamp: firstTradeTime - 60000,
    total: 0,
  };
  allAgentIds.forEach((id) => {
    initialPoint[id] = 0;
    const friendly = getAgentFriendlyName(id);
    initialPoint[friendly] = 0;
  });
  points.push(initialPoint);

  // Cada ordem fechada avança o relógio e adiciona um ponto na curva
  closedTrades.forEach((trade) => {
    const pnl = Number(trade.profit_usd) || 0;
    const aid = trade.agent_id || 'unknown';

    if (cumMap[aid] === undefined) {
      cumMap[aid] = 0;
    }
    cumMap[aid] += pnl;
    runningTotal += pnl;

    const tradeDate = new Date(trade.closed_at || trade.opened_at || Date.now());
    const timeStr = tradeDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const pt: CumulativeEquityPoint = {
      time: timeStr,
      timestamp: tradeDate.getTime(),
      total: Math.round(runningTotal * 100) / 100,
    };

    // Preenche com o id canônico (ex: ops_alpha) e o amigável (ex: Alpha)
    allAgentIds.forEach((id) => {
      const val = Math.round((cumMap[id] || 0) * 100) / 100;
      pt[id] = val;
      const friendly = getAgentFriendlyName(id);
      pt[friendly] = val;
    });

    points.push(pt);
  });

  return points;
}

/**
 * HOOK CENTRAL DE AGREGAÇÃO DE DADOS FINANCEIROS
 * Escuta trades_history e mt5_account_status via Supabase Realtime
 * e processa a agregação matemática de desempenho por agente.
 */
export function useTradingData() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [mt5Account, setMt5Account] = useState<MT5AccountStatus | null>(null);
  const [tradingMode, setTradingMode] = useState<'DEMO' | 'REAL'>('DEMO');
  const [activeAssets, setActiveAssets] = useState<string[]>(['BTCUSD', 'ETHUSD', 'SOLUSD', 'XAUUSD']);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState<boolean>(false);

  // 1. Fetch inicial de trades, mt5_account_status e system_config
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);

      // Busca todas as ordens de trades_history (ordenadas por data)
      const { data: tradesData, error: tradesErr } = await supabase
        .from('trades_history')
        .select('*')
        .order('opened_at', { ascending: false });

      if (tradesErr) throw tradesErr;
      setTrades(tradesData || []);

      // Busca mt5_account_status (linha id = 1)
      const { data: accountData, error: accountErr } = await supabase
        .from('mt5_account_status')
        .select('*')
        .eq('id', 1)
        .limit(1);

      if (accountErr) throw accountErr;
      if (accountData && accountData.length > 0) {
        setMt5Account(accountData[0]);
      } else {
        setMt5Account(null);
      }

      // Busca system_config (linha id = 1)
      const { data: configData, error: configErr } = await supabase
        .from('system_config')
        .select('*')
        .eq('id', 1)
        .limit(1);

      if (!configErr && configData && configData.length > 0) {
        setTradingMode(String(configData[0].trading_mode).toUpperCase() === 'REAL' ? 'REAL' : 'DEMO');
        if (configData[0].active_assets && Array.isArray(configData[0].active_assets)) {
          setActiveAssets(configData[0].active_assets);
        }
      }

      setError(null);
    } catch (err: any) {
      console.error('Erro em useTradingData:', err);
      setError(err?.message || 'Erro ao sincronizar dados de trading');
    } finally {
      setLoading(false);
    }
  }, []);

  // 2. Realtime Subscriptions
  useEffect(() => {
    fetchData();

    const channel = supabase
      .channel('trading_data_realtime_hook')
      // Monitora trades_history
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'trades_history' },
        (payload) => {
          if (payload.eventType === 'INSERT') {
            const newTrade = payload.new as Trade;
            setTrades((prev) => [
              newTrade,
              ...prev.filter((t) => String(t.ticket_mt5) !== String(newTrade.ticket_mt5)),
            ]);
          } else if (payload.eventType === 'UPDATE') {
            const updatedTrade = payload.new as Trade;
            setTrades((prev) =>
              prev.map((t) =>
                String(t.ticket_mt5) === String(updatedTrade.ticket_mt5) ? updatedTrade : t
              )
            );
          } else if (payload.eventType === 'DELETE') {
            const oldTrade = payload.old as Trade;
            setTrades((prev) =>
              prev.filter((t) => String(t.ticket_mt5) !== String(oldTrade.ticket_mt5))
            );
          }
        }
      )
      // Monitora mt5_account_status
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'mt5_account_status' },
        (payload) => {
          if (payload.new) {
            setMt5Account(payload.new as MT5AccountStatus);
          }
        }
      )
      // Monitora system_config
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'system_config' },
        (payload) => {
          if (payload.new) {
            const cfg = payload.new as any;
            setTradingMode(String(cfg.trading_mode).toUpperCase() === 'REAL' ? 'REAL' : 'DEMO');
            if (cfg.active_assets && Array.isArray(cfg.active_assets)) {
              setActiveAssets(cfg.active_assets);
            }
          }
        }
      )
      .subscribe((status) => {
        setIsConnected(status === 'SUBSCRIBED');
      });

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchData]);

  // Função para alternar o modo no Supabase
  const setSystemTradingMode = useCallback(async (mode: 'DEMO' | 'REAL') => {
    try {
      const { error } = await supabase
        .from('system_config')
        .upsert({ id: 1, trading_mode: mode, updated_at: new Date().toISOString() });
      if (error) throw error;
      setTradingMode(mode);
      return true;
    } catch (err) {
      console.error('Erro ao atualizar system_config:', err);
      return false;
    }
  }, []);

  // Função para atualizar active_assets no Supabase
  const updateActiveAssets = useCallback(async (newAssets: string[]) => {
    try {
      const { error } = await supabase
        .from('system_config')
        .update({ active_assets: newAssets, updated_at: new Date().toISOString() })
        .eq('id', 1);
      if (error) throw error;
      setActiveAssets(newAssets);
      return true;
    } catch (err) {
      console.error('Erro ao atualizar active_assets no Supabase:', err);
      return false;
    }
  }, []);

  // 3. A Mágica da Agregação (agentPerformance derivado)
  const agentPerformance = useMemo<AgentPerformanceMap>(() => {
    const performance: AgentPerformanceMap = {};

    // Inicializa os operadores conhecidos com $0.00
    STANDARD_OPS_AGENTS.forEach((agentId) => {
      performance[agentId] = {
        agentId,
        pnl: 0,
        formattedPnL: '$0.00',
        isPositive: false,
        wins: 0,
        losses: 0,
        totalTrades: 0,
        closedTrades: 0,
        openTrades: 0,
        winRate: 0,
        colorClass: 'text-slate-400',
        dotColorClass: 'bg-slate-500',
      };
    });

    if (!trades || !Array.isArray(trades)) {
      return performance;
    }

    trades.forEach((trade) => {
      const aid = trade.agent_id;
      if (!aid) return;

      if (!performance[aid]) {
        performance[aid] = {
          agentId: aid,
          pnl: 0,
          formattedPnL: '$0.00',
          isPositive: false,
          wins: 0,
          losses: 0,
          totalTrades: 0,
          closedTrades: 0,
          openTrades: 0,
          winRate: 0,
          colorClass: 'text-slate-400',
          dotColorClass: 'bg-slate-500',
        };
      }

      performance[aid].totalTrades += 1;
      const status = String(trade.status || '').trim().toUpperCase();

      if (status === 'OPEN') {
        performance[aid].openTrades += 1;
      } else if (status === 'CLOSED') {
        performance[aid].closedTrades += 1;
        const profit = Number(trade.profit_usd) || 0;
        performance[aid].pnl += profit;

        if (profit > 0) {
          performance[aid].wins += 1;
        } else if (profit < 0) {
          performance[aid].losses += 1;
        }
      }
    });

    // Pós-processamento: arredondamento, taxa de acerto e formatação
    Object.keys(performance).forEach((aid) => {
      const item = performance[aid];
      item.pnl = Math.round(item.pnl * 100) / 100;
      const decided = item.wins + item.losses;
      item.winRate = decided > 0 ? Math.round((item.wins / decided) * 100) : 0;

      const fmt = formatPnLValue(item.pnl);
      item.formattedPnL = fmt.formatted;
      item.isPositive = fmt.isPositive;
      item.colorClass = fmt.colorClass;
      item.dotColorClass = fmt.dotColorClass;

      // Também espelha sem o prefixo 'ops_' para garantir resolução perfeita
      const shortId = aid.replace(/^ops_/, '');
      if (!performance[shortId]) {
        performance[shortId] = { ...item, agentId: shortId };
      }
    });

    return performance;
  }, [trades]);

  // 4. Helper seguro para obter performance de qualquer agente
  const getAgentPerformance = useCallback(
    (agentId: string): AgentPerformanceItem => {
      const cleanId = String(agentId || '').trim();
      if (agentPerformance[cleanId]) return agentPerformance[cleanId];
      const withOps = cleanId.startsWith('ops_') ? cleanId : `ops_${cleanId}`;
      if (agentPerformance[withOps]) return agentPerformance[withOps];
      const withoutOps = cleanId.replace(/^ops_/, '');
      if (agentPerformance[withoutOps]) return agentPerformance[withoutOps];

      return {
        agentId: cleanId,
        pnl: 0,
        formattedPnL: '$0.00',
        isPositive: false,
        wins: 0,
        losses: 0,
        totalTrades: 0,
        closedTrades: 0,
        openTrades: 0,
        winRate: 0,
        colorClass: 'text-slate-400',
        dotColorClass: 'bg-slate-500',
      };
    },
    [agentPerformance]
  );

  // 5. Linha temporal derivada para o Recharts
  const timelineData = useMemo(() => {
    return buildPerformanceTimeline(trades, STANDARD_OPS_AGENTS);
  }, [trades]);

  return {
    trades,
    mt5Account,
    tradingMode,
    setSystemTradingMode,
    activeAssets,
    updateActiveAssets,
    agentPerformance,
    getAgentPerformance,
    timelineData,
    buildPerformanceTimeline,
    loading,
    error,
    isConnected,
    refetch: fetchData,
  };
}
