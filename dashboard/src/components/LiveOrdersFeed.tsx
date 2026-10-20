'use client';

import React, { useState } from 'react';
import { 
  History, 
  ArrowUpRight, 
  ArrowDownRight, 
  Info, 
  Filter,
  CheckCircle2,
  Clock,
  Coins
} from 'lucide-react';
import { Trade } from '@/types';

interface LiveOrdersFeedProps {
  trades: Trade[];
}

export const LiveOrdersFeed: React.FC<LiveOrdersFeedProps> = ({ trades }) => {
  const [filterSymbol, setFilterSymbol] = useState<string>('ALL');
  const [selectedRationale, setSelectedRationale] = useState<string | null>(null);

  // Sort trades newest first
  const sortedTrades = [...trades].sort((a, b) => {
    return new Date(b.opened_at || 0).getTime() - new Date(a.opened_at || 0).getTime();
  });

  const filteredTrades = sortedTrades.filter((t) => {
    if (filterSymbol !== 'ALL' && t.symbol !== filterSymbol) return false;
    return true;
  });

  const symbols = ['ALL', 'BTCUSD', 'ETHUSD', 'SOLUSD', 'XAUUSD'];

  const getAgentBadge = (agentId: string) => {
    switch (agentId) {
      case 'ops_alpha':
        return <span className="text-[10px] font-mono text-blue-400 bg-blue-950/60 border border-blue-500/30 px-1.5 py-0.5 rounded">Alpha</span>;
      case 'ops_beta':
        return <span className="text-[10px] font-mono text-purple-400 bg-purple-950/60 border border-purple-500/30 px-1.5 py-0.5 rounded">Beta</span>;
      case 'ops_gamma':
        return <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-500/30 px-1.5 py-0.5 rounded">Gamma</span>;
      default:
        return <span className="text-[10px] font-mono text-slate-400 bg-slate-800 px-1.5 py-0.5 rounded">{agentId}</span>;
    }
  };

  return (
    <div className="rounded-2xl glass-panel p-4 border border-slate-800 shadow-2xl flex flex-col justify-between">
      {/* Header & Filter Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-lg bg-emerald-950/60 border border-emerald-500/30 text-emerald-400">
            <History className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider flex items-center gap-2">
              FEED DE OPERAÇÕES AO VIVO
              <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-500/30">
                {trades.length} ORDENS
              </span>
            </h3>
            <p className="text-xs text-slate-400">
              Execuções transmitidas instantaneamente via Supabase Realtime
            </p>
          </div>
        </div>

        {/* Symbol Filter */}
        <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-lg border border-slate-800 text-[10px] font-mono">
          <Filter className="w-3 h-3 text-slate-500 ml-1" />
          {symbols.map((sym) => (
            <button
              key={sym}
              onClick={() => setFilterSymbol(sym)}
              className={`px-2 py-0.5 rounded transition-all ${
                filterSymbol === sym
                  ? 'bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-500/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {sym}
            </button>
          ))}
        </div>
      </div>

      {/* Orders Table Container */}
      <div className="relative overflow-x-auto max-h-[320px] rounded-xl border border-slate-800/80 bg-slate-950/60">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-slate-900/90 text-slate-400 uppercase text-[9px] sticky top-0 z-10 border-b border-slate-800">
            <tr>
              <th className="px-3 py-2.5">Agente / Ticket</th>
              <th className="px-3 py-2.5">Ativo</th>
              <th className="px-3 py-2.5">Tipo</th>
              <th className="px-3 py-2.5">Entrada</th>
              <th className="px-3 py-2.5">SL / TP</th>
              <th className="px-3 py-2.5">Resultado</th>
              <th className="px-3 py-2.5">Status</th>
              <th className="px-3 py-2.5">Racional Técnico</th>
              <th className="px-3 py-2.5">Horário</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/50 text-slate-300">
            {filteredTrades.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-slate-500 italic">
                  Nenhuma ordem registrada para os filtros selecionados.
                </td>
              </tr>
            ) : (
              filteredTrades.map((trade) => {
                const isBuy = trade.order_type.toUpperCase() === 'BUY';
                const pnl = Number(trade.profit_usd) || 0;
                const isPos = pnl >= 0;
                const isOpen = (trade.status || '').toUpperCase() === 'OPEN';

                return (
                  <tr
                    key={trade.ticket_mt5}
                    className="hover:bg-slate-900/40 transition-colors group"
                  >
                    {/* Agent / Ticket */}
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        {getAgentBadge(trade.agent_id)}
                        <span className="text-[10px] text-slate-500">
                          #{String(trade.ticket_mt5).slice(-5)}
                        </span>
                        {trade.execution_account === 'DEMO' ? (
                          <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber-500/25 text-amber-300 border border-amber-500/50 font-bold">
                            DEMO
                          </span>
                        ) : (
                          <span className="text-[9px] px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold">
                            REAL
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Symbol */}
                    <td className="px-3 py-2 font-bold text-slate-100 flex items-center gap-1">
                      <Coins className="w-3 h-3 text-cyan-400" />
                      {trade.symbol}
                    </td>

                    {/* Order Type */}
                    <td className="px-3 py-2">
                      <span
                        className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded font-bold text-[10px] ${
                          isBuy
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                        }`}
                      >
                        {isBuy ? (
                          <ArrowUpRight className="w-3 h-3" />
                        ) : (
                          <ArrowDownRight className="w-3 h-3" />
                        )}
                        {trade.order_type}
                      </span>
                    </td>

                    {/* Entry Price */}
                    <td className="px-3 py-2 text-slate-200">
                      ${Number(trade.entry_price).toLocaleString()}
                    </td>

                    {/* SL / TP */}
                    <td className="px-3 py-2 text-[10px]">
                      <span className="text-rose-400">${Number(trade.sl).toLocaleString()}</span>
                      <span className="text-slate-600 mx-1">/</span>
                      <span className="text-emerald-400">${Number(trade.tp).toLocaleString()}</span>
                    </td>

                    {/* Profit USD */}
                    <td className="px-3 py-2 font-bold">
                      {isOpen ? (
                        <span className="text-cyan-400 animate-pulse">Em Aberto</span>
                      ) : (
                        <span className={isPos ? 'text-emerald-400' : 'text-rose-400'}>
                          {isPos ? `+$${pnl.toFixed(2)}` : `-$${Math.abs(pnl).toFixed(2)}`}
                        </span>
                      )}
                    </td>

                    {/* Status */}
                    <td className="px-3 py-2">
                      {isOpen ? (
                        <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-500/40">
                          <Clock className="w-2.5 h-2.5 animate-spin" />
                          OPEN
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-700">
                          <CheckCircle2 className="w-2.5 h-2.5 text-emerald-500" />
                          CLOSED
                        </span>
                      )}
                    </td>

                    {/* Rationale */}
                    <td className="px-3 py-2 max-w-[200px]">
                      <div
                        onClick={() => setSelectedRationale(trade.technical_rationale || 'Sem justificativa')}
                        className="truncate text-[10px] text-slate-400 hover:text-cyan-300 cursor-pointer flex items-center gap-1"
                        title={trade.technical_rationale || ''}
                      >
                        <Info className="w-3 h-3 text-cyan-400 flex-shrink-0" />
                        <span className="truncate">{trade.technical_rationale || '—'}</span>
                      </div>
                    </td>

                    {/* Timestamp */}
                    <td className="px-3 py-2 text-[10px] text-slate-500 whitespace-nowrap">
                      {trade.opened_at ? new Date(trade.opened_at).toLocaleTimeString() : '—'}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Rationale Modal / Popup if selected */}
      {selectedRationale && (
        <div className="mt-3 p-3 rounded-xl bg-slate-900/90 border border-cyan-500/40 flex items-start justify-between gap-3 animate-fadeIn">
          <div>
            <div className="text-[10px] font-mono text-cyan-400 uppercase font-bold flex items-center gap-1">
              <Info className="w-3 h-3" />
              <span>JUSTIFICATIVA TÉCNICA QUANT:</span>
            </div>
            <p className="text-xs text-slate-200 mt-1 font-sans leading-relaxed">
              {selectedRationale}
            </p>
          </div>
          <button
            onClick={() => setSelectedRationale(null)}
            className="text-slate-400 hover:text-slate-100 text-xs font-mono px-2 py-0.5 rounded bg-slate-800"
          >
            Fechar
          </button>
        </div>
      )}
    </div>
  );
};
