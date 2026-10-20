'use client';

import React, { useState, useEffect } from 'react';
import { 
  ShieldAlert, 
  ShieldCheck, 
  TrendingUp, 
  TrendingDown, 
  Minus, 
  Radio, 
  Clock, 
  Zap, 
  SlidersHorizontal,
  Coins
} from 'lucide-react';
import { MarketContext } from '@/types';

interface MacroBarProps {
  marketContext: MarketContext | null;
  isConnected: boolean;
  onOpenSimulation: () => void;
}

export const MacroBar: React.FC<MacroBarProps> = ({
  marketContext,
  isConnected,
  onOpenSimulation,
}) => {
  const [time, setTime] = useState<string>('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTime(now.toISOString().slice(11, 19) + ' UTC');
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const cryptoVal = marketContext?.crypto_sentiment ?? 0;
  const goldVal = marketContext?.gold_sentiment ?? 0;
  const isRedFlag = Boolean(marketContext?.red_flag_pause_trading);
  const keyDriver =
    marketContext?.key_driver ||
    'Aguardando telemetria do News Desk e feeds globais de liquidez...';

  // Helper for thermometer bar percentage (-10 to +10 => 0% to 100%)
  const getPercentage = (val: number) => {
    const clamped = Math.max(-10, Math.min(10, val));
    return ((clamped + 10) / 20) * 100;
  };

  const getSentimentDetails = (val: number) => {
    if (val >= 4) {
      return {
        label: 'BULLISH / OTIMISTA',
        color: 'text-emerald-400',
        bg: 'bg-emerald-500/20 border-emerald-500/40',
        barColor: 'from-emerald-500 to-teal-400',
        icon: <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />,
      };
    } else if (val <= -4) {
      return {
        label: 'BEARISH / PESSIMISTA',
        color: 'text-rose-400',
        bg: 'bg-rose-500/20 border-rose-500/40',
        barColor: 'from-rose-600 to-red-400',
        icon: <TrendingDown className="w-3.5 h-3.5 text-rose-400" />,
      };
    } else {
      return {
        label: 'NEUTRO / LATERAL',
        color: 'text-amber-400',
        bg: 'bg-amber-500/20 border-amber-500/40',
        barColor: 'from-amber-500 to-yellow-400',
        icon: <Minus className="w-3.5 h-3.5 text-amber-400" />,
      };
    }
  };

  const cryptoStyle = getSentimentDetails(cryptoVal);
  const goldStyle = getSentimentDetails(goldVal);

  return (
    <header className="relative w-full glass-panel rounded-2xl p-4 border border-slate-800 shadow-2xl mb-4">
      {/* Top row: Title, Connection Status, UTC clock, Sim Button */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-800/80">
        
        {/* Brand / Fund Title */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-700 flex items-center justify-center shadow-[0_0_15px_#00f0ff] border border-cyan-300">
            <Zap className="w-5 h-5 text-slate-950 font-bold" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-black tracking-wider text-slate-100 flex items-center gap-1.5">
                QUANT OFFICE AI
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                  CENTRO DE COMANDO
                </span>
              </h1>
            </div>
            <p className="text-[11px] font-mono text-slate-400">
              SISTEMA MULTI-AGENTE AUTÔNOMO • METATRADER 5 & SUPABASE REALTIME
            </p>
          </div>
        </div>

        {/* Global Market Status Badge */}
        <div className="flex items-center gap-3">
          {isRedFlag ? (
            <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl border border-red-500/80 text-red-200 red-flag-alert shadow-lg">
              <ShieldAlert className="w-5 h-5 text-red-400 animate-pulse" />
              <div>
                <div className="text-xs font-black tracking-widest uppercase">
                  RED FLAG / PAUSA MACRO
                </div>
                <div className="text-[9px] font-mono text-red-300">
                  CIRCUIT BREAKER ATIVADO • NOVAS ORDENS BLOQUEADAS
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl border border-emerald-500/40 bg-emerald-950/40 text-emerald-200 shadow-[0_0_12px_rgba(16,185,129,0.2)]">
              <div className="relative">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                <div className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
              </div>
              <div>
                <div className="text-xs font-black tracking-widest uppercase text-emerald-300">
                  STATUS NORMAL
                </div>
                <div className="text-[9px] font-mono text-emerald-400/80">
                  OPERAÇÃO TOTALMENTE ATIVA
                </div>
              </div>
            </div>
          )}

          {/* Realtime WebSocket Indicator */}
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-[11px] font-mono">
            <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-500'}`} />
            <span className={isConnected ? 'text-emerald-400' : 'text-rose-400'}>
              {isConnected ? 'REALTIME ON' : 'CONNECTING...'}
            </span>
          </div>

          {/* Clock */}
          <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-[11px] font-mono text-slate-300">
            <Clock className="w-3.5 h-3.5 text-cyan-400" />
            <span>{time || '--:--:-- UTC'}</span>
          </div>

          {/* Simulation Trigger Button */}
          <button
            onClick={onOpenSimulation}
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white text-xs font-bold font-mono tracking-wide shadow-[0_0_15px_rgba(6,182,212,0.4)] transition-all hover:scale-105 active:scale-95 border border-cyan-400/50 cursor-pointer"
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span>SIMULAR EVENTO</span>
          </button>
        </div>

      </div>

      {/* Bottom row: Thermometers and Dominant Key Driver */}
      <div className="mt-3.5 grid grid-cols-1 md:grid-cols-12 gap-3.5 items-center">
        
        {/* Thermometer 1: Crypto Sentiment */}
        <div className="md:col-span-3 p-2.5 rounded-xl bg-slate-950/70 border border-slate-800 flex flex-col justify-between">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-1.5 text-xs font-mono font-semibold text-slate-300">
              <Coins className="w-3.5 h-3.5 text-amber-400" />
              <span>SENTIMENTO CRIPTO</span>
            </div>
            <div className="flex items-center gap-1">
              {cryptoStyle.icon}
              <span className={`text-xs font-mono font-bold ${cryptoStyle.color}`}>
                {cryptoVal > 0 ? `+${cryptoVal}` : cryptoVal} / 10
              </span>
            </div>
          </div>

          {/* Gauge Meter (-10 to +10) */}
          <div className="relative w-full h-2.5 bg-slate-900 rounded-full overflow-hidden border border-slate-800 my-1">
            {/* Center tick indicator for 0 */}
            <div className="absolute top-0 bottom-0 left-1/2 w-0.5 bg-slate-700 z-10" />
            <div 
              className={`h-full bg-gradient-to-r ${cryptoStyle.barColor} transition-all duration-500 rounded-full`}
              style={{ width: `${getPercentage(cryptoVal)}%` }}
            />
          </div>

          <div className="flex justify-between items-center text-[9px] font-mono text-slate-500">
            <span>-10 (Extremo Medo)</span>
            <span className={`font-semibold ${cryptoStyle.color}`}>{cryptoStyle.label}</span>
            <span>+10 (Ganância)</span>
          </div>
        </div>

        {/* Thermometer 2: Gold Sentiment */}
        <div className="md:col-span-3 p-2.5 rounded-xl bg-slate-950/70 border border-slate-800 flex flex-col justify-between">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-1.5 text-xs font-mono font-semibold text-slate-300">
              <Zap className="w-3.5 h-3.5 text-yellow-400" />
              <span>SENTIMENTO OURO (XAU)</span>
            </div>
            <div className="flex items-center gap-1">
              {goldStyle.icon}
              <span className={`text-xs font-mono font-bold ${goldStyle.color}`}>
                {goldVal > 0 ? `+${goldVal}` : goldVal} / 10
              </span>
            </div>
          </div>

          {/* Gauge Meter (-10 to +10) */}
          <div className="relative w-full h-2.5 bg-slate-900 rounded-full overflow-hidden border border-slate-800 my-1">
            <div className="absolute top-0 bottom-0 left-1/2 w-0.5 bg-slate-700 z-10" />
            <div 
              className={`h-full bg-gradient-to-r ${goldStyle.barColor} transition-all duration-500 rounded-full`}
              style={{ width: `${getPercentage(goldVal)}%` }}
            />
          </div>

          <div className="flex justify-between items-center text-[9px] font-mono text-slate-500">
            <span>-10 (Bearish)</span>
            <span className={`font-semibold ${goldStyle.color}`}>{goldStyle.label}</span>
            <span>+10 (Bullish)</span>
          </div>
        </div>

        {/* Dominant Headline / Driver */}
        <div className="md:col-span-6 p-2.5 rounded-xl bg-slate-950/80 border border-cyan-500/20 flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-950/60 border border-cyan-500/30 text-cyan-400 flex-shrink-0">
            <Radio className="w-4 h-4 animate-pulse" />
          </div>
          <div className="overflow-hidden">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-cyan-400 font-bold">
                DRIVER DOMINANTE MACRO:
              </span>
              <span className="text-[9px] font-mono text-slate-500">
                {marketContext?.created_at ? new Date(marketContext.created_at).toLocaleTimeString() : 'Sincronizado'}
              </span>
            </div>
            <p className="text-xs text-slate-200 truncate font-sans font-medium" title={keyDriver}>
              "{keyDriver}"
            </p>
          </div>
        </div>

      </div>
    </header>
  );
};
