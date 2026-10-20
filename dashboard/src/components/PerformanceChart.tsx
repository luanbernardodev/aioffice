'use client';

import React, { useMemo, useState, useEffect } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import { TrendingUp, Activity } from 'lucide-react';
import { Trade, CumulativeEquityPoint, AgentStatus } from '@/types';
import {
  buildPerformanceTimeline,
  STANDARD_OPS_AGENTS,
  getAgentFriendlyName,
} from '@/hooks/useTradingData';

interface PerformanceChartProps {
  trades: Trade[];
  agents?: AgentStatus[];
}

interface AgentSeriesMeta {
  id: string;
  name: string;
  shortLabel: string;
  color: string;
  borderClass: string;
  textClass: string;
}

// Cores e estilos por linhagem de estratégia
const LINEAGE_THEMES: Record<string, { color: string; borderClass: string; textClass: string }> = {
  alpha: { color: '#3B82F6', borderClass: 'border-blue-500/30', textClass: 'text-blue-400' },
  delta: { color: '#06B6D4', borderClass: 'border-cyan-500/30', textClass: 'text-cyan-400' },
  beta: { color: '#A855F7', borderClass: 'border-purple-500/30', textClass: 'text-purple-400' },
  epsilon: { color: '#6366F1', borderClass: 'border-indigo-500/30', textClass: 'text-indigo-400' },
  gamma: { color: '#10B981', borderClass: 'border-emerald-500/30', textClass: 'text-emerald-400' },
};

const DEFAULT_THEME = { color: '#F97316', borderClass: 'border-amber-500/30', textClass: 'text-amber-400' };

export const PerformanceChart: React.FC<PerformanceChartProps> = ({ trades = [], agents = [] }) => {
  const [filterPeriod, setFilterPeriod] = useState<'ALL' | '24H' | '7D'>('ALL');
  const [showTotal, setShowTotal] = useState<boolean>(true);
  const [currentTime, setCurrentTime] = useState<number>(0);

  useEffect(() => {
    setCurrentTime(Date.now());
  }, []);

  // 1. Identifica os agentes operacionais visíveis (exclui demitidos 'FIRED')
  const visibleAgents: AgentSeriesMeta[] = useMemo(() => {
    const activeFromProps = (agents || []).filter(
      (a) =>
        (a.sector === 1 || a.agent_id.startsWith('ops_')) &&
        (a.current_state || '').toUpperCase() !== 'FIRED'
    );

    let baseList: { id: string; name: string }[] = [];

    if (activeFromProps.length > 0) {
      baseList = activeFromProps.map((a) => ({ id: a.agent_id, name: a.name }));
    } else {
      // Identifica a partir dos IDs em trades
      const tradeAgentIds = Array.from(new Set((trades || []).map((t) => t.agent_id).filter(Boolean)));
      if (tradeAgentIds.length > 0) {
        baseList = tradeAgentIds.map((id) => ({
          id,
          name: `${getAgentFriendlyName(id)} (${id})`,
        }));
      } else {
        baseList = STANDARD_OPS_AGENTS.map((id) => ({
          id,
          name: `Ops ${getAgentFriendlyName(id)}`,
        }));
      }
    }

    return baseList.map((item) => {
      const lineage = item.id.replace(/_v\d+$/i, '').replace(/^ops_/, '').toLowerCase();
      const theme = LINEAGE_THEMES[lineage] || DEFAULT_THEME;
      const shortLabel = getAgentFriendlyName(item.id);

      return {
        id: item.id,
        name: item.name,
        shortLabel,
        color: theme.color,
        borderClass: theme.borderClass,
        textClass: theme.textClass,
      };
    });
  }, [agents, trades]);

  // 2. Computa a curva de capital cumulativa cronológica usando a função central
  const chartData = useMemo(() => {
    if (!trades || trades.length === 0) return [];

    // Filtra período se aplicável
    const now = currentTime || Date.now();
    const periodFilteredTrades = trades.filter((t) => {
      if (filterPeriod === 'ALL') return true;
      const tTime = new Date(t.closed_at || t.opened_at || 0).getTime();
      if (filterPeriod === '24H') return now - tTime <= 24 * 3600 * 1000;
      if (filterPeriod === '7D') return now - tTime <= 7 * 24 * 3600 * 1000;
      return true;
    });

    const targetAgentIds = visibleAgents.map((a) => a.id);
    return buildPerformanceTimeline(periodFilteredTrades, targetAgentIds);
  }, [trades, visibleAgents, filterPeriod, currentTime]);

  const lastPoint: CumulativeEquityPoint = chartData.length > 0
    ? chartData[chartData.length - 1]
    : { time: '', timestamp: 0, total: 0 };

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="rounded-xl glass-panel p-3 border border-slate-700 shadow-2xl text-xs font-mono bg-slate-950/95">
          <div className="text-slate-400 font-semibold mb-2 border-b border-slate-800 pb-1 flex items-center justify-between gap-4">
            <span>Hora: {label}</span>
            <span className="text-cyan-400">Curva de Capital</span>
          </div>
          <div className="space-y-1.5">
            {payload.map((entry: any, index: number) => {
              const val = Number(entry.value) || 0;
              const isPos = val >= 0;
              return (
                <div key={`item-${index}`} className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: entry.color }} />
                    <span className="text-slate-200 capitalize">{entry.name}:</span>
                  </div>
                  <span className={`font-bold ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {isPos ? `+$${val.toFixed(2)}` : `-$${Math.abs(val).toFixed(2)}`}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="rounded-2xl glass-panel p-4 border border-slate-800 shadow-2xl bg-slate-950/80">
      {/* Header and Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-blue-950/60 border border-blue-500/30 text-blue-400">
            <TrendingUp className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider">
              CURVA DE CAPITAL COMPARATIVA (PNL ACUMULADO)
            </h3>
            <p className="text-xs text-slate-400">
              Desempenho dinâmico sincronizado com ordens fechadas no Supabase
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2 self-end sm:self-auto font-mono text-xs">
          <div className="flex rounded-lg bg-slate-900 border border-slate-800 p-0.5">
            {(['ALL', '7D', '24H'] as const).map((period) => (
              <button
                key={period}
                onClick={() => setFilterPeriod(period)}
                className={`px-2.5 py-1 rounded-md transition ${
                  filterPeriod === period
                    ? 'bg-blue-600 text-white font-bold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {period}
              </button>
            ))}
          </div>

          <button
            onClick={() => setShowTotal(!showTotal)}
            className={`px-2.5 py-1 rounded-lg border transition ${
              showTotal
                ? 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40'
                : 'bg-slate-900 text-slate-400 border-slate-800'
            }`}
          >
            Total Fundo
          </button>
        </div>
      </div>

      {/* Quick Summary Chips Dinâmicos mapeando os agentes ativos */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mb-3">
        {visibleAgents.map((ag) => {
          const val = Number(lastPoint[ag.id] ?? lastPoint[ag.shortLabel]) || 0;
          const isPos = val >= 0;

          return (
            <div key={ag.id} className={`p-2 rounded-lg bg-slate-950/80 border ${ag.borderClass}`}>
              <div className={`text-[9px] font-mono ${ag.textClass} flex items-center justify-between`}>
                <span className="truncate">{ag.shortLabel}</span>
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: ag.color }} />
              </div>
              <div className={`text-xs font-mono font-bold mt-0.5 ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                {isPos ? `+$${val.toFixed(2)}` : `-$${Math.abs(val).toFixed(2)}`}
              </div>
            </div>
          );
        })}

        {/* Chip Total do Fundo */}
        <div className="p-2 rounded-lg bg-slate-950/80 border border-yellow-500/30">
          <div className="text-[9px] font-mono text-yellow-400 flex items-center justify-between">
            <span>Lucro Líquido</span>
            <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
          </div>
          <div className={`text-xs font-mono font-bold mt-0.5 ${(lastPoint.total || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {(lastPoint.total || 0) >= 0
              ? `+$${(lastPoint.total || 0).toFixed(2)}`
              : `-$${Math.abs(lastPoint.total || 0).toFixed(2)}`}
          </div>
        </div>
      </div>

      {/* Recharts Container com Linhas Geradas via .map() */}
      <div className="w-full h-64 mt-2">
        {chartData.length === 0 ? (
          <div className="w-full h-full flex flex-col items-center justify-center rounded-xl bg-slate-900/30 border border-slate-800 text-slate-500 font-mono text-xs gap-2">
            <Activity className="w-6 h-6 text-slate-600 animate-pulse" />
            <span>Nenhuma ordem fechada encontrada no banco de dados.</span>
            <span className="text-[10px] text-slate-600">
              O gráfico desenhará a evolução assim que as ordens forem concluídas no MT5.
            </span>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 15, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" opacity={0.6} />
              <XAxis
                dataKey="time"
                stroke="#64748b"
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
              />
              <YAxis
                stroke="#64748b"
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
                tickFormatter={(val) => `$${val}`}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: '11px', fontFamily: 'monospace', paddingTop: '8px' }}
              />

              {/* Linhas dinâmicas por operador ativo (sem hardcoding de IDs) */}
              {visibleAgents.map((ag) => (
                <Line
                  key={ag.id}
                  type="monotone"
                  dataKey={ag.id}
                  name={ag.shortLabel}
                  stroke={ag.color}
                  strokeWidth={2.5}
                  dot={{ r: 2.5, fill: ag.color }}
                  activeDot={{ r: 5, fill: ag.color }}
                />
              ))}

              {/* Combined Total Line (Yellow/Gold) */}
              {showTotal && (
                <Line
                  type="monotone"
                  dataKey="total"
                  name="Total Fundo"
                  stroke="#FACC15"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  dot={false}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
};

export default PerformanceChart;
