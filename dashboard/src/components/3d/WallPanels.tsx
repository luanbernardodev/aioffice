'use client';

import React from 'react';
import { Html } from '@react-three/drei';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts';
import {
  TrendingUp,
  Radio,
  Maximize2,
  History
} from 'lucide-react';
import { Trade, MarketContext, AgentStatus } from '@/types';
import { buildPerformanceTimeline } from '@/hooks/useTradingData';

// -------------------------------------------------------------
// TELÃO PAREDE 1: Performance Equity Curve (Mini Compact Card)
// -------------------------------------------------------------
interface WallScreen1Props {
  position: [number, number, number];
  rotation?: [number, number, number];
  trades: Trade[];
  onExpand?: () => void;
}

export const WallScreenPerformance: React.FC<WallScreen1Props> = ({
  position,
  rotation = [0, 0, 0],
  trades,
  onExpand,
}) => {
  const chartData = React.useMemo(() => {
    return buildPerformanceTimeline(trades, ['ops_alpha', 'ops_beta', 'ops_gamma']);
  }, [trades]);

  const { aSum, bSum, gSum } = React.useMemo(() => {
    let a = 0;
    let b = 0;
    let g = 0;
    (trades || []).forEach((t) => {
      if (String(t.status || '').trim().toUpperCase() === 'CLOSED') {
        const p = Number(t.profit_usd) || 0;
        if (t.agent_id === 'ops_alpha') a += p;
        if (t.agent_id === 'ops_beta') b += p;
        if (t.agent_id === 'ops_gamma') g += p;
      }
    });
    return { aSum: Math.round(a * 100) / 100, bSum: Math.round(b * 100) / 100, gSum: Math.round(g * 100) / 100 };
  }, [trades]);

  return (
    <group position={position} rotation={rotation}>
      {/* 3D Bezel Frame matching compact proportions */}
      <mesh position={[0, 0, -0.04]}>
        <boxGeometry args={[6.8, 4.2, 0.08]} />
        <meshStandardMaterial color="#0f172a" roughness={0.3} metalness={0.8} />
      </mesh>
      {/* Cyan Neon Edge */}
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[6.86, 4.26, 0.02]} />
        <meshStandardMaterial color="#00f0ff" emissive="#00f0ff" emissiveIntensity={0.8} />
      </mesh>

      {/* Embedded Compact HTML Panel */}
      <Html
        transform
        position={[0, 0, 0.05]}
        distanceFactor={8}
        zIndexRange={[5, 0]}
        style={{ pointerEvents: 'auto', transformOrigin: 'center' }}
        className="select-none"
      >
        <div style={{ width: 260, height: 160 }} className="w-[260px] h-[160px] bg-slate-950/95 border border-cyan-500/40 rounded-xl p-2.5 flex flex-col justify-between shadow-2xl text-slate-100 font-mono">
          {/* Header */}
          <div className="flex items-center justify-between pb-1 border-b border-slate-800">
            <div className="flex items-center gap-1.5">
              <TrendingUp className="w-3 h-3 text-cyan-400" />
              <span className="text-[9px] font-bold tracking-wide text-cyan-300">
                TELÃO 1: PERFORMANCE
              </span>
            </div>
            {onExpand && (
              <button
                onClick={onExpand}
                className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition cursor-pointer"
                title="Expandir em Tela Cheia"
              >
                <Maximize2 className="w-2.5 h-2.5" />
              </button>
            )}
          </div>

          {/* Quick Metrics */}
          <div className="grid grid-cols-3 gap-1 my-0.5">
            <div className="px-1 py-0.5 rounded bg-slate-900 border border-blue-500/30 text-center">
              <span className="text-[7px] text-blue-400 block font-bold">ALPHA</span>
              <span className={`text-[8px] font-bold ${aSum >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {aSum >= 0 ? `+$${aSum.toFixed(0)}` : `-$${Math.abs(aSum).toFixed(0)}`}
              </span>
            </div>
            <div className="px-1 py-0.5 rounded bg-slate-900 border border-purple-500/30 text-center">
              <span className="text-[7px] text-purple-400 block font-bold">BETA</span>
              <span className={`text-[8px] font-bold ${bSum >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {bSum >= 0 ? `+$${bSum.toFixed(0)}` : `-$${Math.abs(bSum).toFixed(0)}`}
              </span>
            </div>
            <div className="px-1 py-0.5 rounded bg-slate-900 border border-emerald-500/30 text-center">
              <span className="text-[7px] text-emerald-400 block font-bold">GAMMA</span>
              <span className={`text-[8px] font-bold ${gSum >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {gSum >= 0 ? `+$${gSum.toFixed(0)}` : `-$${Math.abs(gSum).toFixed(0)}`}
              </span>
            </div>
          </div>

          {/* Compact LineChart */}
          <div className="w-full flex items-center justify-center">
            <LineChart width={240} height={80} data={chartData} margin={{ top: 2, right: 5, left: -32, bottom: 0 }}>
              <CartesianGrid strokeDasharray="2 2" stroke="#1e293b" opacity={0.5} />
              <XAxis dataKey="time" stroke="#64748b" fontSize={6} tickLine={false} />
              <YAxis stroke="#64748b" fontSize={6} tickFormatter={(v) => `$${v}`} tickLine={false} />
              <Line type="monotone" dataKey="ops_alpha" stroke="#3B82F6" strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="ops_beta" stroke="#A855F7" strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="ops_gamma" stroke="#10B981" strokeWidth={1.5} dot={false} />
            </LineChart>
          </div>
        </div>
      </Html>
    </group>
  );
};

// -------------------------------------------------------------
// TELÃO PAREDE 2: Radar Macro & Notícias (Mini Compact Card)
// -------------------------------------------------------------
interface WallScreen2Props {
  position: [number, number, number];
  rotation?: [number, number, number];
  marketContext: MarketContext | null;
  onExpand?: () => void;
}

export const WallScreenMacro: React.FC<WallScreen2Props> = ({
  position,
  rotation = [0, 0, 0],
  marketContext,
  onExpand,
}) => {
  const cryptoVal = marketContext?.crypto_sentiment ?? 0;
  const goldVal = marketContext?.gold_sentiment ?? 0;
  const isRedFlag = Boolean(marketContext?.red_flag_pause_trading);
  const keyDriver = marketContext?.key_driver || 'Aguardando telemetria do News Desk...';
  const getPercent = (v: number) => ((Math.max(-10, Math.min(10, v)) + 10) / 20) * 100;

  return (
    <group position={position} rotation={rotation}>
      {/* 3D Bezel Frame matching compact proportions */}
      <mesh position={[0, 0, -0.04]}>
        <boxGeometry args={[6.8, 4.2, 0.08]} />
        <meshStandardMaterial color="#0f172a" roughness={0.3} metalness={0.8} />
      </mesh>
      {/* Amber Neon Edge */}
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[6.86, 4.26, 0.02]} />
        <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={0.8} />
      </mesh>

      <Html
        transform
        position={[0, 0, 0.05]}
        distanceFactor={8}
        zIndexRange={[5, 0]}
        style={{ pointerEvents: 'auto', transformOrigin: 'center' }}
        className="select-none"
      >
        <div style={{ width: 260, height: 160 }} className="w-[260px] h-[160px] bg-slate-950/95 border border-amber-500/40 rounded-xl p-2.5 flex flex-col justify-between shadow-2xl text-slate-100 font-mono">
          {/* Header */}
          <div className="flex items-center justify-between pb-1 border-b border-slate-800">
            <div className="flex items-center gap-1.5">
              <Radio className="w-3 h-3 text-amber-400 animate-pulse" />
              <span className="text-[9px] font-bold tracking-wide text-amber-300">
                TELÃO 2: RADAR MACRO
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              {isRedFlag ? (
                <span className="px-1.5 py-0.2 rounded bg-rose-950 border border-rose-500 text-rose-300 text-[7px] font-bold">
                  RED FLAG
                </span>
              ) : (
                <span className="px-1.5 py-0.2 rounded bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 text-[7px] font-bold">
                  NORMAL
                </span>
              )}
              {onExpand && (
                <button
                  onClick={onExpand}
                  className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition cursor-pointer"
                  title="Expandir em Tela Cheia"
                >
                  <Maximize2 className="w-2.5 h-2.5" />
                </button>
              )}
            </div>
          </div>

          {/* Thermometers Grid */}
          <div className="grid grid-cols-2 gap-1.5 my-1">
            <div className="p-1 rounded bg-slate-900 border border-slate-800">
              <div className="flex justify-between text-[7px] mb-0.5">
                <span className="text-amber-400 font-bold">Cripto:</span>
                <span className="font-bold">{cryptoVal > 0 ? `+${cryptoVal}` : cryptoVal} / 10</span>
              </div>
              <div className="w-full h-1.5 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                <div
                  className="h-full bg-gradient-to-r from-rose-500 via-amber-400 to-emerald-400 rounded-full"
                  style={{ width: `${getPercent(cryptoVal)}%` }}
                />
              </div>
            </div>

            <div className="p-1 rounded bg-slate-900 border border-slate-800">
              <div className="flex justify-between text-[7px] mb-0.5">
                <span className="text-yellow-400 font-bold">Ouro:</span>
                <span className="font-bold">{goldVal > 0 ? `+${goldVal}` : goldVal} / 10</span>
              </div>
              <div className="w-full h-1.5 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                <div
                  className="h-full bg-gradient-to-r from-rose-500 via-yellow-400 to-emerald-400 rounded-full"
                  style={{ width: `${getPercent(goldVal)}%` }}
                />
              </div>
            </div>
          </div>

          {/* Driver Dominante */}
          <div className="p-1.5 rounded-lg bg-slate-900/90 border border-amber-500/30 flex-1 my-0.5 overflow-hidden">
            <span className="text-[7px] text-amber-400 font-bold tracking-wider block">
              DRIVER DOMINANTE:
            </span>
            <p className="text-[8px] font-sans text-slate-200 line-clamp-2 leading-tight mt-0.5">
              "{keyDriver}"
            </p>
          </div>

          <div className="text-[7px] text-slate-500 flex justify-between items-center pt-0.5 border-t border-slate-800">
            <span>News Desk Feed</span>
            <span className="text-cyan-400">Setor 2</span>
          </div>
        </div>
      </Html>
    </group>
  );
};

// -------------------------------------------------------------
// TELÃO PAREDE 3: Live Trade Tape & Risco (Mini Compact Card)
// -------------------------------------------------------------
interface WallScreen3Props {
  position: [number, number, number];
  rotation?: [number, number, number];
  trades: Trade[];
  agents: AgentStatus[];
  onExpand?: () => void;
}

export const WallScreenTradeTape: React.FC<WallScreen3Props> = ({
  position,
  rotation = [0, 0, 0],
  trades,
  onExpand,
}) => {
  const recentTrades = trades.slice(0, 3);

  return (
    <group position={position} rotation={rotation}>
      {/* 3D Bezel Frame matching compact proportions */}
      <mesh position={[0, 0, -0.04]}>
        <boxGeometry args={[6.8, 4.2, 0.08]} />
        <meshStandardMaterial color="#0f172a" roughness={0.3} metalness={0.8} />
      </mesh>
      {/* Emerald Neon Edge */}
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[6.86, 4.26, 0.02]} />
        <meshStandardMaterial color="#10b981" emissive="#10b981" emissiveIntensity={0.8} />
      </mesh>

      <Html
        transform
        position={[0, 0, 0.05]}
        distanceFactor={8}
        zIndexRange={[5, 0]}
        style={{ pointerEvents: 'auto', transformOrigin: 'center' }}
        className="select-none"
      >
        <div style={{ width: 260, height: 160 }} className="w-[260px] h-[160px] bg-slate-950/95 border border-emerald-500/40 rounded-xl p-2.5 flex flex-col justify-between shadow-2xl text-slate-100 font-mono">
          {/* Header */}
          <div className="flex items-center justify-between pb-1 border-b border-slate-800">
            <div className="flex items-center gap-1.5">
              <History className="w-3 h-3 text-emerald-400" />
              <span className="text-[9px] font-bold tracking-wide text-emerald-300">
                TELÃO 3: TAPE DE ORDENS
              </span>
            </div>
            {onExpand && (
              <button
                onClick={onExpand}
                className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition cursor-pointer"
                title="Expandir em Tela Cheia"
              >
                <Maximize2 className="w-2.5 h-2.5" />
              </button>
            )}
          </div>

          {/* Orders Mini Table */}
          <div className="overflow-hidden rounded border border-slate-800 my-0.5">
            <table className="w-full text-[7px] text-left">
              <thead className="bg-slate-900 text-slate-400 uppercase">
                <tr>
                  <th className="p-0.5">Ativo</th>
                  <th className="p-0.5">Tipo</th>
                  <th className="p-0.5">Entrada</th>
                  <th className="p-0.5">PnL</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {recentTrades.map((t) => {
                  const isBuy = t.order_type === 'BUY';
                  const pnl = Number(t.profit_usd) || 0;
                  return (
                    <tr key={t.ticket_mt5}>
                      <td className="p-0.5 font-bold text-slate-200">{t.symbol}</td>
                      <td className="p-0.5">
                        <span className={isBuy ? 'text-emerald-400' : 'text-rose-400'}>
                          {t.order_type}
                        </span>
                      </td>
                      <td className="p-0.5">${Number(t.entry_price).toLocaleString()}</td>
                      <td className={`p-0.5 font-bold ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {pnl >= 0 ? `+$${pnl.toFixed(0)}` : `-$${Math.abs(pnl).toFixed(0)}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Multipliers */}
          <div className="pt-1 border-t border-slate-800 flex items-center justify-between text-[7px]">
            <span className="text-slate-400">CRO:</span>
            <div className="flex items-center gap-1.5">
              <span className="text-blue-400 font-bold">Alpha 1.5x</span>
              <span className="text-purple-400 font-bold">Beta 0.0x</span>
              <span className="text-emerald-400 font-bold">Gamma 1.5x</span>
            </div>
          </div>
        </div>
      </Html>
    </group>
  );
};

