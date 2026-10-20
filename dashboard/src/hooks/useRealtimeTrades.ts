'use client';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { supabase } from '@/lib/supabase';
import { Trade } from '@/types';
import { calculateNetPnLByAgent, getAgentNetPnL, getAgentPerformanceMetrics, formatPnL } from '@/lib/pnlUtils';

export { calculateNetPnLByAgent, getAgentNetPnL, getAgentPerformanceMetrics, formatPnL };

export function useRealtimeTrades(initialLimit = 200) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = useCallback(async () => {
    try {
      setLoading(true);
      const { data, error: err } = await supabase
        .from('trades_history')
        .select('*')
        .order('opened_at', { ascending: false })
        .limit(initialLimit);

      if (err) throw err;
      setTrades(data || []);
      setError(null);
    } catch (err: any) {
      console.error('Erro ao buscar trades_history:', err);
      setError(err?.message || 'Erro ao carregar trades');
    } finally {
      setLoading(false);
    }
  }, [initialLimit]);

  useEffect(() => {
    fetchTrades();

    const channel = supabase
      .channel('realtime_trades_history_hook')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'trades_history' },
        (payload) => {
          if (payload.eventType === 'INSERT') {
            const newTrade = payload.new as Trade;
            setTrades((prev) => [newTrade, ...prev.filter((t) => t.ticket_mt5 !== newTrade.ticket_mt5)]);
          } else if (payload.eventType === 'UPDATE') {
            const updatedTrade = payload.new as Trade;
            setTrades((prev) =>
              prev.map((t) => (t.ticket_mt5 === updatedTrade.ticket_mt5 ? updatedTrade : t))
            );
          } else if (payload.eventType === 'DELETE') {
            const oldTrade = payload.old as Trade;
            setTrades((prev) => prev.filter((t) => t.ticket_mt5 !== oldTrade.ticket_mt5));
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchTrades]);

  // Net PnL acumulado agregado por agent_id (somente trades fechadas)
  const netPnLByAgent = useMemo(() => calculateNetPnLByAgent(trades), [trades]);

  return { trades, setTrades, netPnLByAgent, loading, error, refetch: fetchTrades };
}

