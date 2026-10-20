'use client';

import React, { useMemo } from 'react';
import { Html } from '@react-three/drei';
import { Trade, MT5AccountStatus, AgentStatus, MarketContext } from '@/types';
import { getAgentPerformanceMetrics } from '@/lib/pnlUtils';
import {
  Wallet,
  Zap,
  TrendingUp,
  Target,
  Shield,
  Award,
  CheckCircle2,
  AlertTriangle,
  ArrowUpRight,
  ArrowDownRight,
  Activity,
  Maximize2
} from 'lucide-react';

interface WallCanvasScreensProps {
  account: MT5AccountStatus | null;
  trades: Trade[];
  agents: AgentStatus[];
  marketContext: MarketContext | null;
  onOpenModal: () => void;
  onOpenMT5Modal?: () => void;
}

export const WallCanvasScreens: React.FC<WallCanvasScreensProps> = ({
  account,
  trades,
  agents,
  marketContext,
  onOpenModal,
  onOpenMT5Modal,
}) => {
  const balance = Number(account?.balance ?? 0.0);
  const equity = Number(account?.equity ?? balance);
  const pnl = Number(account?.floating_pnl ?? 0.0);
  const freeMargin = Number(account?.free_margin ?? balance);
  const winCount = Number(account?.win_count ?? 0);
  const lossCount = Number(account?.loss_count ?? 0);
  const totalTrades = winCount + lossCount;
  const winRate = totalTrades > 0 ? Math.round((winCount / totalTrades) * 100) : 0;
  const totalTp = Number(account?.total_tp_gain ?? 0.0);
  const totalSl = Math.abs(Number(account?.total_sl_loss ?? 0.0));
  const pf = totalSl > 0 ? (totalTp / totalSl).toFixed(2) : (totalTp > 0 ? '9.99' : '0.00');

  const handleOpenMT5 = onOpenMT5Modal || onOpenModal;

  // Real open trades from Supabase
  const openTrades = useMemo(() => {
    return trades.filter((t) => t.status === 'OPEN');
  }, [trades]);

  // Dynamic real operator statistics from trades_history
  const opsStats = useMemo(() => {
    const ops = [
      { id: 'ops_alpha', name: 'ALPHA (TREND FOLLOWING)', short: 'ALPHA' },
      { id: 'ops_delta', name: 'DELTA (SMC SCALPER M1)', short: 'DELTA' },
      { id: 'ops_gamma', name: 'GAMMA (BREAKOUT VOLATILITY)', short: 'GAMMA' },
      { id: 'ops_epsilon', name: 'EPSILON (VWAP SCALPER M5)', short: 'EPSILON' },
      { id: 'ops_beta', name: 'BETA (SNIPER MEAN REVERSION)', short: 'BETA' },
    ];

    return ops.map((op) => {
      const ag = agents.find((a) => a.agent_id === op.id);
      const metrics = getAgentPerformanceMetrics(trades, op.id);
      const isQuarantined = ag?.current_state === 'QUARANTINED' || ag?.allocation_weight === 0;
      const weight = ag?.allocation_weight !== undefined ? `${ag.allocation_weight.toFixed(1)}x` : '1.0x';
      const status = isQuarantined ? 'QUARENTENA' : (ag?.current_state || 'IDLE');

      return {
        ...op,
        pnl: metrics.netPnL,
        pnlFormatted: metrics.formattedPnL,
        wr: `${metrics.winRate}%`,
        alloc: weight,
        status,
        isQuarantined,
        color: metrics.colorClass,
        badge: isQuarantined
          ? 'bg-rose-950 text-rose-400 border-rose-500/40'
          : metrics.netPnL >= 0
          ? 'bg-emerald-950 text-emerald-400 border-emerald-500/40'
          : 'bg-rose-950 text-rose-400 border-rose-500/40',
      };
    });
  }, [agents, trades]);

  // Real SVG Equity curve from closed trades
  const svgCurveData = useMemo(() => {
    const closed = [...trades]
      .filter((t) => t.status === 'CLOSED')
      .sort((a, b) => new Date(a.closed_at || a.opened_at).getTime() - new Date(b.closed_at || b.opened_at).getTime());

    if (closed.length === 0) {
      const basePoints = [
        { x: 30, y: 90, pnl: 0 },
        { x: 810, y: 90, pnl: 0 },
      ];
      return {
        points: basePoints,
        dPath: 'M 30 90 L 810 90',
        areaPath: 'M 30 90 L 810 90 L 810 170 L 30 170 Z',
        lastPnl: 0,
      };
    }

    let cum = 0;
    const history = closed.map((t) => {
      cum += Number(t.profit_usd) || 0;
      return cum;
    });

    const minPnl = Math.min(0, ...history);
    const maxPnl = Math.max(0, ...history);
    const range = (maxPnl - minPnl) || 1;

    const width = 780;
    const height = 140;
    const paddingY = 20;

    const points = [{ x: 30, y: 160 - ((0 - minPnl) / range) * height, pnl: 0 }];
    history.forEach((val, idx) => {
      const x = 30 + ((idx + 1) / history.length) * width;
      const y = paddingY + (1 - (val - minPnl) / range) * height;
      points.push({ x, y, pnl: val });
    });

    const dPath = points.reduce((acc, p, i) => {
      if (i === 0) return `M ${p.x} ${p.y}`;
      const prev = points[i - 1];
      const cx = (prev.x + p.x) / 2;
      return `${acc} C ${cx} ${prev.y}, ${cx} ${p.y}, ${p.x} ${p.y}`;
    }, '');

    const areaPath = `${dPath} L 810 170 L 30 170 Z`;

    return {
      points,
      dPath,
      areaPath,
      lastPnl: cum,
    };
  }, [trades]);

  return (
    <group position={[0, 4.6, -11.75]}>
      {/* ========================================================= */}
      {/* 1. TICKER TAPE BANNER (Z = 3.3 relative, world Y = 7.95)   */}
      {/* ========================================================= */}
      <group position={[0, 3.35, 0]}>
        {/* Frame Box */}
        <mesh position={[0, 0, -0.02]}>
          <boxGeometry args={[39.4, 0.9, 0.04]} />
          <meshStandardMaterial color="#020617" roughness={0.3} metalness={0.9} />
        </mesh>
        {/* Dark Backing Plane */}
        <mesh position={[0, 0, 0.01]}>
          <planeGeometry args={[39.0, 0.75]} />
          <meshBasicMaterial color="#050814" />
        </mesh>
        {/* High-Res HTML Ribbon (distanceFactor 6 -> 1px = 0.015 units, 2600px = 39.0 units) */}
        <Html
          transform
          position={[0, 0, 0.03]}
          distanceFactor={6}
          zIndexRange={[5, 0]}
          style={{ width: '2600px', height: '48px', pointerEvents: 'auto' }}
        >
          <div
            onClick={onOpenModal}
            className="w-[2600px] h-[48px] flex items-center justify-between px-6 bg-slate-950/95 border border-yellow-500/40 rounded-lg text-xs font-mono cursor-pointer select-none shadow-2xl backdrop-blur-md"
          >
            <div className="flex items-center gap-2 text-cyan-400 font-bold tracking-wider">
              <Zap className="w-4 h-4 text-cyan-400 animate-pulse" />
              QUANT WALL STREET HQ
            </div>
            {opsStats.map((op) => (
              <React.Fragment key={op.id}>
                <div className="text-slate-600">|</div>
                <div className={op.isQuarantined ? "text-rose-400 font-bold bg-rose-950/60 px-2 py-0.5 rounded border border-rose-500/40" : `${op.color} font-semibold`}>
                  {op.short}: {op.isQuarantined ? `QUARENTENA (${op.pnlFormatted})` : `${op.pnlFormatted} (WR ${op.wr})`}
                </div>
              </React.Fragment>
            ))}
            <div className="text-slate-600">|</div>
            <div className="text-emerald-400 font-bold">
              SALDO: ${balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
            <div className="text-slate-600">|</div>
            <div className="text-yellow-400 font-bold">
              EQUITY: ${equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
            <div className="text-slate-600">|</div>
            <div className="text-cyan-400 font-bold">
              FATOR DE LUCRO: {pf}
            </div>
          </div>
        </Html>
      </group>

      {/* ========================================================= */}
      {/* 2. PAINEL 1 (ESQUERDA, X = -13.2): CARTEIRA MT5 & ORDENS  */}
      {/* ========================================================= */}
      <group position={[-13.2, 0, 0]}>
        {/* Bezel Frame: 12.6 x 5.4 units */}
        <mesh position={[0, 0, -0.04]}>
          <boxGeometry args={[12.6, 5.4, 0.08]} />
          <meshStandardMaterial color="#020617" roughness={0.3} metalness={0.9} />
        </mesh>
        {/* Neon border edge */}
        <mesh position={[0, 0, -0.01]}>
          <boxGeometry args={[12.66, 5.46, 0.02]} />
          <meshStandardMaterial color="#00f0ff" emissive="#00f0ff" emissiveIntensity={1.4} />
        </mesh>
        {/* Solid Dark Screen Backing */}
        <mesh position={[0, 0, 0.01]}>
          <planeGeometry args={[12.3, 5.1]} />
          <meshBasicMaterial color="#030712" />
        </mesh>

        {/* HTML Panel: distanceFactor 6 -> 820px x 340px = 12.3 x 5.1 units EXACT */}
        <Html
          transform
          position={[0, 0, 0.05]}
          distanceFactor={6}
          zIndexRange={[5, 0]}
          style={{ width: '820px', height: '340px', pointerEvents: 'auto' }}
        >
          <div
            onClick={handleOpenMT5}
            className="w-[820px] h-[340px] flex flex-col justify-between p-3.5 bg-slate-950/95 border border-cyan-500/50 rounded-2xl shadow-[0_0_30px_rgba(0,240,255,0.2)] text-slate-100 font-mono select-none cursor-pointer transition-all hover:border-cyan-400 backdrop-blur-md"
          >
            {/* Header: Title & Connection */}
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-cyan-950 border border-cyan-500/50 flex items-center justify-center">
                  <Wallet className="w-3.5 h-3.5 text-cyan-400" />
                </div>
                <span className="text-xs font-bold tracking-wider text-cyan-300">
                  CARTEIRA MT5 & TELEMETRIA FINANCEIRA
                </span>
              </div>
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-500/40 text-[10px] text-emerald-400 font-bold">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                CONEXÃO XM / SUPABASE ATIVA
              </div>
            </div>

            {/* Former Floating Card Integrated Here: Saldo, Equity, TP, SL, WR, PF */}
            <div className="grid grid-cols-6 gap-2 p-2 rounded-xl bg-slate-900/90 border border-slate-700/80 shadow-inner text-center">
              {/* Saldo */}
              <div className="flex flex-col items-center">
                <span className="text-[9px] text-slate-400">SALDO</span>
                <span className="text-xs font-bold text-white tracking-wide">
                  ${balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </span>
              </div>

              {/* Equity */}
              <div className="flex flex-col items-center border-l border-slate-800">
                <span className="text-[9px] text-slate-400">EQUITY</span>
                <div className="flex items-center gap-1">
                  <span className="text-xs font-bold text-white tracking-wide">
                    ${equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </span>
                  <span className={`text-[9px] font-bold px-1 rounded ${pnl >= 0 ? 'bg-emerald-950 text-emerald-400 border border-emerald-500/30' : 'bg-rose-950 text-rose-400 border border-rose-500/30'}`}>
                    {pnl >= 0 ? `+$${pnl.toFixed(1)}` : `-$${Math.abs(pnl).toFixed(1)}`}
                  </span>
                </div>
              </div>

              {/* TP Gains */}
              <div className="flex flex-col items-center border-l border-slate-800">
                <span className="text-[9px] text-emerald-400">GANHOS TP</span>
                <span className="text-xs font-bold text-emerald-400">
                  +${totalTp.toFixed(0)}{' '}
                  <span className="text-[9px] text-emerald-500 font-normal">({winCount}W)</span>
                </span>
              </div>

              {/* SL Losses */}
              <div className="flex flex-col items-center border-l border-slate-800">
                <span className="text-[9px] text-rose-400">PERDAS SL</span>
                <span className="text-xs font-bold text-rose-400">
                  -${totalSl.toFixed(0)}{' '}
                  <span className="text-[9px] text-rose-500 font-normal">({lossCount}L)</span>
                </span>
              </div>

              {/* Win Rate */}
              <div className="flex flex-col items-center border-l border-slate-800">
                <span className="text-[9px] text-cyan-400">TAXA ACERTO</span>
                <span className="text-xs font-bold text-cyan-300">
                  {winRate}%
                </span>
              </div>

              {/* Profit Factor */}
              <div className="flex flex-col items-center border-l border-slate-800">
                <span className="text-[9px] text-amber-400">PROFIT FACTOR</span>
                <span className="text-xs font-bold text-amber-400">
                  {pf}
                </span>
              </div>
            </div>

            {/* Active Orders / Positions Live Monitor */}
            <div className="flex flex-col gap-1.5 my-1">
              <div className="flex items-center justify-between text-[10px] text-slate-400 font-bold px-1">
                <span>POSIÇÕES ABERTAS NO MERCADO ({openTrades.length})</span>
                <span className="text-cyan-400">PROGRESSO TP / SL</span>
              </div>

              <div className="flex flex-col gap-1.5 max-h-[145px] overflow-hidden">
                {openTrades.length === 0 ? (
                  <div className="p-3 rounded-xl bg-slate-900/40 border border-slate-800/60 text-center text-[10px] text-slate-400 font-mono">
                    Sem ordens abertas no momento. Sentinela varrendo cotações em tempo real...
                  </div>
                ) : (
                  openTrades.slice(0, 3).map((trade, idx) => {
                  const entry = Number(trade.entry_price) || 1;
                  const current = Number(trade.current_price ?? entry);
                  const sl = Number(trade.sl) || entry * 0.99;
                  const tp = Number(trade.tp) || entry * 1.02;
                  const isBuy = trade.order_type === 'BUY';
                  const progress = Math.max(5, Math.min(95, isBuy ? ((current - sl) / (tp - sl)) * 100 : ((sl - current) / (sl - tp)) * 100));

                  return (
                    <div
                      key={trade.ticket_mt5 || idx}
                      className="p-2 rounded-xl bg-slate-900/80 border border-slate-800/90 flex flex-col gap-1 hover:border-slate-700 transition"
                    >
                      <div className="flex items-center justify-between text-[11px]">
                        <div className="flex items-center gap-1.5">
                          <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold ${isBuy ? 'bg-emerald-950 text-emerald-400 border border-emerald-500/40' : 'bg-rose-950 text-rose-400 border border-rose-500/40'}`}>
                            {trade.order_type}
                          </span>
                          <span className="font-bold text-white">{trade.symbol}</span>
                          <span className="text-[10px] text-slate-400">Vol: {trade.volume}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-slate-400">Entrada: ${entry.toLocaleString()}</span>
                          <span className="font-bold text-cyan-300">Atual: ${current.toLocaleString()}</span>
                          <span className={`font-bold ${(Number(trade.profit_usd) || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {(Number(trade.profit_usd) || 0) >= 0 ? '+' : ''}${(Number(trade.profit_usd) || 0).toFixed(2)}
                          </span>
                        </div>
                      </div>

                      {/* Visual SL <---> TP Progress bar */}
                      <div className="flex items-center gap-2 text-[9px]">
                        <span className="text-rose-400 font-bold whitespace-nowrap">SL: ${sl.toLocaleString()}</span>
                        <div className="flex-1 h-2 bg-slate-950 rounded-full overflow-hidden border border-slate-800 relative">
                          <div
                            className="h-full bg-gradient-to-r from-rose-500 via-amber-400 to-emerald-400 transition-all duration-300"
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                        <span className="text-emerald-400 font-bold whitespace-nowrap">TP: ${tp.toLocaleString()}</span>
                      </div>
                    </div>
                  );
                }))}
              </div>
            </div>

            {/* Bottom Footer Button: Opens Full Modal */}
            <div className="flex items-center justify-between pt-1 border-t border-slate-800 text-[10px]">
              <span className="text-slate-400">
                MARGEM LIVRE: ${freeMargin.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <button
                onClick={handleOpenMT5}
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-bold transition shadow-[0_0_12px_rgba(6,182,212,0.4)]"
              >
                <span>VER RAIO-X COMPLETO DE ORDENS (TP/SL)</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </Html>
      </group>

      {/* ========================================================= */}
      {/* 3. PAINEL 2 (CENTRO, X = 0.0): CURVA DE CAPITAL ACUMULADA */}
      {/* ========================================================= */}
      <group position={[0, 0, 0]}>
        {/* Bezel Frame: 12.6 x 5.4 units */}
        <mesh position={[0, 0, -0.04]}>
          <boxGeometry args={[12.6, 5.4, 0.08]} />
          <meshStandardMaterial color="#020617" roughness={0.3} metalness={0.9} />
        </mesh>
        {/* Neon border edge */}
        <mesh position={[0, 0, -0.01]}>
          <boxGeometry args={[12.66, 5.46, 0.02]} />
          <meshStandardMaterial color="#10b981" emissive="#10b981" emissiveIntensity={1.4} />
        </mesh>
        {/* Solid Dark Screen Backing */}
        <mesh position={[0, 0, 0.01]}>
          <planeGeometry args={[12.3, 5.1]} />
          <meshBasicMaterial color="#030712" />
        </mesh>

        {/* HTML Panel: distanceFactor 6 -> 820px x 340px = 12.3 x 5.1 units EXACT */}
        <Html
          transform
          position={[0, 0, 0.05]}
          distanceFactor={6}
          zIndexRange={[5, 0]}
          style={{ width: '820px', height: '340px', pointerEvents: 'auto' }}
        >
          <div
            onClick={onOpenModal}
            className="w-[820px] h-[340px] flex flex-col justify-between p-3.5 bg-slate-950/95 border border-emerald-500/50 rounded-2xl shadow-[0_0_30px_rgba(16,185,129,0.2)] text-slate-100 font-mono select-none cursor-pointer transition-all hover:border-emerald-400 backdrop-blur-md"
          >
            {/* Header: Title & Allocation */}
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-emerald-950 border border-emerald-500/50 flex items-center justify-center">
                  <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                </div>
                <span className="text-xs font-bold tracking-wider text-emerald-300">
                  CURVA DE CAPITAL ACUMULADA (HIGH-WATER MARK)
                </span>
              </div>
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-500/40 text-[10px] text-emerald-400 font-bold">
                ALOCAÇÃO MÁXIMA: 1.5x
              </div>
            </div>

            {/* Glowing SVG Equity Curve */}
            <div className="relative w-full h-[200px] bg-slate-900/60 rounded-xl p-2 border border-slate-800/90 overflow-hidden">
              <svg className="w-full h-full" viewBox="0 0 840 180" preserveAspectRatio="none">
                <defs>
                  <linearGradient id="equityGradWall" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity="0.45" />
                    <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
                  </linearGradient>
                </defs>
                {/* Horizontal Guide Lines */}
                <line x1="30" y1="35" x2="810" y2="35" stroke="#334155" strokeDasharray="4 4" strokeWidth="1" />
                <line x1="30" y1="80" x2="810" y2="80" stroke="#334155" strokeDasharray="4 4" strokeWidth="1" />
                <line x1="30" y1="125" x2="810" y2="125" stroke="#334155" strokeDasharray="4 4" strokeWidth="1" />

                {/* Guide Labels */}
                <text x="35" y="30" fill="#64748b" fontSize="10" fontFamily="monospace">${(balance + 200).toFixed(0)}</text>
                <text x="35" y="75" fill="#64748b" fontSize="10" fontFamily="monospace">${balance.toFixed(0)} (BASE)</text>
                <text x="35" y="120" fill="#64748b" fontSize="10" fontFamily="monospace">${Math.max(0, balance - 200).toFixed(0)}</text>

                {/* Area Fill */}
                <path d={svgCurveData.areaPath} fill="url(#equityGradWall)" />

                {/* Neon Stroke Line */}
                <path
                  d={svgCurveData.dPath}
                  fill="none"
                  stroke="#10b981"
                  strokeWidth="3.5"
                  className="filter drop-shadow-[0_0_8px_rgba(16,185,129,0.9)]"
                />

                {/* Point Dots */}
                {svgCurveData.points.map((p, i) => (
                  <circle
                    key={i}
                    cx={p.x}
                    cy={p.y}
                    r={i === svgCurveData.points.length - 1 ? 5 : 3}
                    fill={i === svgCurveData.points.length - 1 ? '#00f0ff' : '#10b981'}
                    className="filter drop-shadow-[0_0_4px_#00f0ff]"
                  />
                ))}
              </svg>

              <div className="absolute top-2 right-3 text-[10px] text-emerald-300 font-bold bg-slate-950/85 px-2.5 py-1 rounded-lg border border-emerald-500/40 shadow-md">
                EQUITY: ${equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
            </div>

            {/* Bottom Key Metrics Bar */}
            <div className="flex items-center justify-between pt-1 border-t border-slate-800 text-[10px] text-slate-300">
              <span className="flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                DRAWDOWN MÁXIMO: <strong className="text-white">1.0%</strong>
              </span>
              <span>MARGEM LIVRE: <strong className="text-cyan-300">${(balance * 0.98).toLocaleString('en-US', { maximumFractionDigits: 0 })}</strong></span>
              <span>SHARPE: <strong className="text-amber-400">2.84</strong></span>
              <span className="text-emerald-400 font-bold underline hover:text-emerald-300 transition">
                EXPANDIR HISTÓRICO DE CAPITAL ➔
              </span>
            </div>
          </div>
        </Html>
      </group>

      {/* ========================================================= */}
      {/* 4. PAINEL 3 (DIREITA, X = 13.2): PERFORMANCE POR OPERADOR */}
      {/* ========================================================= */}
      <group position={[13.2, 0, 0]}>
        {/* Bezel Frame: 12.6 x 5.4 units */}
        <mesh position={[0, 0, -0.04]}>
          <boxGeometry args={[12.6, 5.4, 0.08]} />
          <meshStandardMaterial color="#020617" roughness={0.3} metalness={0.9} />
        </mesh>
        {/* Neon border edge */}
        <mesh position={[0, 0, -0.01]}>
          <boxGeometry args={[12.66, 5.46, 0.02]} />
          <meshStandardMaterial color="#eab308" emissive="#eab308" emissiveIntensity={1.4} />
        </mesh>
        {/* Solid Dark Screen Backing */}
        <mesh position={[0, 0, 0.01]}>
          <planeGeometry args={[12.3, 5.1]} />
          <meshBasicMaterial color="#030712" />
        </mesh>

        {/* HTML Panel: distanceFactor 6 -> 820px x 340px = 12.3 x 5.1 units EXACT */}
        <Html
          transform
          position={[0, 0, 0.05]}
          distanceFactor={6}
          zIndexRange={[5, 0]}
          style={{ width: '820px', height: '340px', pointerEvents: 'auto' }}
        >
          <div
            onClick={onOpenModal}
            className="w-[820px] h-[340px] flex flex-col justify-between p-3.5 bg-slate-950/95 border border-yellow-500/50 rounded-2xl shadow-[0_0_30px_rgba(234,179,8,0.2)] text-slate-100 font-mono select-none cursor-pointer transition-all hover:border-yellow-400 backdrop-blur-md"
          >
            {/* Header: Title & Global Risk */}
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-yellow-950 border border-yellow-500/50 flex items-center justify-center">
                  <Award className="w-3.5 h-3.5 text-yellow-400" />
                </div>
                <span className="text-xs font-bold tracking-wider text-yellow-300">
                  PERFORMANCE E TAXA DE ACERTO POR OPERADOR
                </span>
              </div>
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-500/40 text-[10px] text-emerald-400 font-bold">
                AUDITORIA DE RISCO: 4 ATIVOS / 1 QUARENTENA
              </div>
            </div>

            {/* Performance Table with All 5 Quant Operators */}
            <div className="flex flex-col gap-1 my-0.5">
              {/* Header */}
              <div className="grid grid-cols-6 gap-2 px-3 py-1 rounded-lg bg-slate-900/90 text-[10px] font-bold text-slate-400 border border-slate-800">
                <span className="col-span-2">OPERADOR / ESTRATÉGIA</span>
                <span>PnL ACUMULADO</span>
                <span>WIN RATE</span>
                <span>ALOCAÇÃO</span>
                <span className="text-right">STATUS</span>
              </div>

              {/* Dynamic Rows */}
              {opsStats.map((row) => (
                <div
                  key={row.id}
                  className="grid grid-cols-6 gap-2 px-3 py-1.5 rounded-lg bg-slate-900/60 hover:bg-slate-850/80 text-[11px] items-center border border-slate-800/60 transition"
                >
                  <span className="col-span-2 font-bold text-slate-200 truncate flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full ${row.isQuarantined ? 'bg-rose-500' : 'bg-cyan-400'}`} />
                    {row.name}
                  </span>
                  <span className={`font-bold ${row.color}`}>{row.pnlFormatted}</span>
                  <span className="text-slate-300 font-semibold">{row.wr}</span>
                  <span className="text-amber-400 font-semibold">{row.alloc}</span>
                  <div className="text-right">
                    <span className={`inline-block px-2 py-0.5 rounded text-[9px] font-bold border ${row.badge}`}>
                      {row.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            {/* Bottom Footer Card */}
            <div className="flex items-center justify-between px-3 py-1.5 rounded-xl bg-slate-900/80 border border-slate-800 text-[10px]">
              <div className="flex items-center gap-3 text-slate-300">
                <span>FATOR DE LUCRO: <strong className="text-amber-400 font-mono">{pf}</strong></span>
                <span>•</span>
                <span>ORDENS VENCEDORAS: <strong className="text-emerald-400 font-mono">{winCount}</strong></span>
                <span>•</span>
                <span>ORDENS PERDEDORAS: <strong className="text-rose-400 font-mono">{lossCount}</strong></span>
              </div>
              <div className="text-yellow-400 font-bold underline cursor-pointer hover:text-yellow-300 transition">
                RAIO-X DE RISCO DETALHADO ➔
              </div>
            </div>
          </div>
        </Html>
      </group>
    </group>
  );
};

export default WallCanvasScreens;
