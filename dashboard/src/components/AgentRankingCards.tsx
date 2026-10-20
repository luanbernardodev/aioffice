'use client';

import React from 'react';
import { 
  Trophy, 
  Percent, 
  DollarSign, 
  Scale, 
  BarChart3, 
  Lock, 
  Zap, 
  Activity,
  Layers
} from 'lucide-react';
import { AgentStatus, Trade } from '@/types';
import { getAgentPerformanceMetrics } from '@/lib/pnlUtils';

interface AgentRankingCardsProps {
  agents: AgentStatus[];
  trades: Trade[];
}

const THEMES: Record<string, { color: string; border: string; accent: string }> = {
  alpha: { color: 'blue', border: 'border-blue-500/40', accent: 'text-blue-400' },
  delta: { color: 'teal', border: 'border-teal-500/40', accent: 'text-teal-400' },
  beta: { color: 'purple', border: 'border-purple-500/40', accent: 'text-purple-400' },
  epsilon: { color: 'indigo', border: 'border-indigo-500/40', accent: 'text-indigo-400' },
  gamma: { color: 'emerald', border: 'border-emerald-500/40', accent: 'text-emerald-400' },
};

const DEFAULT_CARD_THEME = { color: 'amber', border: 'border-amber-500/40', accent: 'text-amber-400' };

export const AgentRankingCards: React.FC<AgentRankingCardsProps> = ({ agents, trades }) => {
  // Filtra estritamente os operadores ativos do Setor 1 ignorando demitidos ('FIRED')
  const activeOps = agents.filter(
    (a) =>
      (a.sector === 1 || a.agent_id.startsWith('ops_')) &&
      (a.current_state || '').toUpperCase() !== 'FIRED'
  );

  // Lista de agentes para renderização com fallback inicial se vazio
  const agentsToRender = activeOps.length > 0 ? activeOps : [
    { agent_id: 'ops_alpha', name: 'Ops Alpha (Trend)', sector: 1, current_state: 'IDLE', allocation_weight: 1.0 },
    { agent_id: 'ops_delta', name: 'Ops Delta (SMC Scalper)', sector: 1, current_state: 'IDLE', allocation_weight: 1.0 },
    { agent_id: 'ops_beta', name: 'Ops Beta (Sniper)', sector: 1, current_state: 'IDLE', allocation_weight: 1.0 },
    { agent_id: 'ops_epsilon', name: 'Ops Epsilon (VWAP Scalp)', sector: 1, current_state: 'IDLE', allocation_weight: 1.0 },
    { agent_id: 'ops_gamma', name: 'Ops Gamma (Breakout)', sector: 1, current_state: 'IDLE', allocation_weight: 1.0 },
  ] as AgentStatus[];

  const agentCards = agentsToRender.map((agent) => {
    const lineage = agent.agent_id.replace(/_v\d+$/i, '').replace(/^ops_/, '').toLowerCase();
    const theme = THEMES[lineage] || DEFAULT_CARD_THEME;

    // Consome rigorosamente a mesma agregação matemática centralizada
    const metrics = getAgentPerformanceMetrics(trades, agent.agent_id);

    return {
      id: agent.agent_id,
      name: agent.name,
      color: theme.color,
      border: theme.border,
      accent: theme.accent,
      agent,
      winRate: metrics.winRate,
      totalProfit: metrics.netPnL,
      profitFactor: metrics.profitFactor,
      allocationWeight: agent.allocation_weight ?? 1.0,
      currentState: agent.current_state || 'IDLE',
      totalTrades: metrics.totalTrades,
      winCount: metrics.winCount,
      lossCount: metrics.lossCount,
    };
  });

  // Sort by Total Profit descending for ranking badge
  const rankedCards = [...agentCards].sort((a, b) => b.totalProfit - a.totalProfit);

  return (
    <div className="rounded-2xl glass-panel p-4 border border-slate-800 shadow-2xl">
      <div className="flex items-center justify-between pb-3 mb-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-lg bg-yellow-950/60 border border-yellow-500/30 text-yellow-400">
            <Trophy className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider">
              RANKING & METRICAS DE OPERADORES
            </h3>
            <p className="text-xs text-slate-400">
              Win Rate, Fator de Lucro e Alocação de Capital autorizada pelo CRO
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3.5">
        {rankedCards.map((item, index) => {
          const isQuarantined = item.currentState === 'QUARANTINED';
          const isImmunized = (item.agent.last_thought || '').includes('Imunizada') || (item.agent.last_thought || '').includes('Imunizado');
          const isPos = item.totalProfit >= 0;

          return (
            <div
              key={item.id}
              className={`relative rounded-xl p-3.5 bg-slate-950/70 border ${
                isQuarantined ? 'border-rose-500/60 bg-rose-950/10' : item.border
              } transition-all duration-300 hover:scale-[1.02] shadow-xl flex flex-col justify-between`}
            >
              {/* Rank Position Badge */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className={`w-6 h-6 rounded-md flex items-center justify-center font-mono font-bold text-xs ${
                    index === 0 ? 'bg-yellow-500 text-slate-950 shadow-[0_0_8px_#eab308]' :
                    index === 1 ? 'bg-slate-300 text-slate-950' :
                    index === 2 ? 'bg-amber-800 text-amber-100' :
                    'bg-slate-800 text-slate-300'
                  }`}>
                    #{index + 1}
                  </div>
                  <div>
                    <h4 className="text-xs font-bold text-slate-100">{item.name}</h4>
                    <span className="text-[10px] font-mono text-slate-400">ID: {item.id}</span>
                  </div>
                </div>

                {/* State & Vaccine Badges */}
                <div className="flex flex-col items-end gap-1">
                  <span className={`text-[9px] px-2 py-0.5 rounded font-mono font-bold border ${
                    isQuarantined
                      ? 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                      : item.currentState === 'EXECUTING'
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 animate-pulse'
                      : item.currentState === 'ANALYZING'
                      ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                      : 'bg-slate-800 text-slate-300 border-slate-700'
                  }`}>
                    {item.currentState}
                  </span>
                  {isImmunized && !isQuarantined && (
                    <span className="text-[8px] px-1.5 py-0.2 rounded font-mono font-bold bg-emerald-950/90 text-emerald-300 border border-emerald-500/50 shadow-[0_0_8px_#10b981]">
                      🛡️ Imunizado
                    </span>
                  )}
                </div>
              </div>

              {/* 4 Core Quant Metrics Grid */}
              <div className="grid grid-cols-2 gap-2 my-2">
                
                {/* Win Rate */}
                <div className="p-2 rounded-lg bg-slate-900/80 border border-slate-800">
                  <div className="text-[9px] font-mono text-slate-400 flex items-center gap-1">
                    <Percent className="w-3 h-3 text-cyan-400" />
                    <span>WIN RATE</span>
                  </div>
                  <div className="text-base font-bold font-mono text-cyan-300 mt-0.5">
                    {item.winRate}%
                  </div>
                  <div className="text-[8px] font-mono text-slate-500 mt-0.5">
                    {item.winCount}W / {item.lossCount}L ({item.totalTrades} trades)
                  </div>
                </div>

                {/* Total Lucro ($) */}
                <div className="p-2 rounded-lg bg-slate-900/80 border border-slate-800">
                  <div className="text-[9px] font-mono text-slate-400 flex items-center gap-1">
                    <DollarSign className="w-3 h-3 text-emerald-400" />
                    <span>LUCRO TOTAL</span>
                  </div>
                  <div className={`text-base font-bold font-mono mt-0.5 ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {isPos ? `+$${item.totalProfit.toFixed(2)}` : `-$${Math.abs(item.totalProfit).toFixed(2)}`}
                  </div>
                  <div className="text-[8px] font-mono text-slate-500 mt-0.5">
                    Acumulado USD
                  </div>
                </div>

                {/* Profit Factor */}
                <div className="p-2 rounded-lg bg-slate-900/80 border border-slate-800">
                  <div className="text-[9px] font-mono text-slate-400 flex items-center gap-1">
                    <Scale className="w-3 h-3 text-amber-400" />
                    <span>FATOR DE LUCRO</span>
                  </div>
                  <div className={`text-base font-bold font-mono mt-0.5 ${item.profitFactor >= 1.5 ? 'text-emerald-400' : item.profitFactor >= 1.0 ? 'text-amber-400' : 'text-rose-400'}`}>
                    {item.profitFactor.toFixed(2)}
                  </div>
                  <div className="text-[8px] font-mono text-slate-500 mt-0.5">
                    {item.profitFactor >= 1.5 ? 'Excelente (>1.5)' : item.profitFactor >= 1.0 ? 'Aceitável' : 'Abaixo do Limiar'}
                  </div>
                </div>

                {/* Allocation Weight */}
                <div className="p-2 rounded-lg bg-slate-900/80 border border-slate-800">
                  <div className="text-[9px] font-mono text-slate-400 flex items-center gap-1">
                    <BarChart3 className="w-3 h-3 text-purple-400" />
                    <span>PESO DA MÃO</span>
                  </div>
                  <div className={`text-base font-bold font-mono mt-0.5 ${item.allocationWeight === 0 ? 'text-rose-400' : 'text-yellow-400'}`}>
                    {item.allocationWeight.toFixed(1)}x
                  </div>
                  <div className="text-[8px] font-mono text-slate-500 mt-0.5">
                    {item.allocationWeight === 0 ? 'Suspenso pelo CRO' : 'Autorizado'}
                  </div>
                </div>

              </div>

              {/* Progress bar of Allocation Weight */}
              <div className="mt-2 pt-2 border-t border-slate-800/80">
                <div className="flex justify-between items-center text-[9px] font-mono text-slate-400 mb-1">
                  <span>Alocação de Risco:</span>
                  <span className="text-slate-200 font-bold">{Math.round((item.allocationWeight / 2.0) * 100)}% do máx</span>
                </div>
                <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      item.allocationWeight === 0
                        ? 'bg-rose-500'
                        : 'bg-gradient-to-r from-cyan-500 to-emerald-400'
                    }`}
                    style={{ width: `${Math.min(100, (item.allocationWeight / 2.0) * 100)}%` }}
                  />
                </div>
              </div>

            </div>
          );
        })}
      </div>
    </div>
  );
};
