'use client';

import React, { useState, useEffect } from 'react';
import { 
  ShieldAlert, 
  ShieldCheck, 
  Clock, 
  SlidersHorizontal, 
  Users, 
  RotateCcw, 
  Terminal, 
  ChevronDown,
  ChevronRight, 
  Activity, 
  Zap, 
  Lock, 
  Cpu,
  AlertTriangle,
  FlaskConical
} from 'lucide-react';
import { AgentStatus, MarketContext, Trade } from '@/types';
import { supabase } from '@/lib/supabase';
import { Header } from '@/components/Header';

interface CommandHUDProps {
  agents: AgentStatus[];
  marketContext: MarketContext | null;
  trades: Trade[];
  isConnected: boolean;
  tradingMode?: 'DEMO' | 'REAL';
  onToggleTradingMode?: (mode: 'DEMO' | 'REAL') => Promise<boolean | void> | boolean | void;
  onOpenSimulation: () => void;
  onOpenMT5Modal?: () => void;
  onSelectAgent: (agent: AgentStatus) => void;
  onTriggerMeeting: () => void;
  onTriggerReset: () => void;
  onTestNewsDelivery: () => void;
  onTestAuditDelivery: () => void;
  onTestCalibration?: () => void;
  onTestCRODirective?: () => void;
  isMeetingActive: boolean;
}

export const CommandHUD: React.FC<CommandHUDProps> = ({
  agents,
  marketContext,
  trades,
  isConnected,
  tradingMode,
  onToggleTradingMode,
  onOpenSimulation,
  onOpenMT5Modal,
  onSelectAgent,
  onTriggerMeeting,
  onTriggerReset,
  onTestNewsDelivery,
  onTestAuditDelivery,
  onTestCalibration,
  onTestCRODirective,
  isMeetingActive,
}) => {
  const [time, setTime] = useState<string>('');
  const [collapsedLeft, setCollapsedLeft] = useState(false);
  const [showActions, setShowActions] = useState(false);
  const [localMode, setLocalMode] = useState<'DEMO' | 'REAL'>('DEMO');
  const [showConfirmRealModal, setShowConfirmRealModal] = useState<boolean>(false);
  const [isSwitching, setIsSwitching] = useState<boolean>(false);

  useEffect(() => {
    const updateTime = () => {
      setTime(new Date().toISOString().slice(11, 19) + ' UTC');
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  // Sincronização em tempo real de system_config
  useEffect(() => {
    const fetchMode = async () => {
      try {
        const { data } = await supabase
          .from('system_config')
          .select('trading_mode')
          .eq('id', 1)
          .limit(1);
        if (data && data.length > 0) {
          setLocalMode(String(data[0].trading_mode).toUpperCase() === 'REAL' ? 'REAL' : 'DEMO');
        }
      } catch (err) {
        console.error('Erro ao ler system_config:', err);
      }
    };
    fetchMode();

    const channel = supabase
      .channel('system_config_hud_listener')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'system_config' },
        (payload) => {
          if (payload.new) {
            const cfg = payload.new as any;
            setLocalMode(String(cfg.trading_mode).toUpperCase() === 'REAL' ? 'REAL' : 'DEMO');
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const currentMode = tradingMode || localMode;

  const performModeChange = async (targetMode: 'DEMO' | 'REAL') => {
    setIsSwitching(true);
    try {
      if (onToggleTradingMode) {
        await onToggleTradingMode(targetMode);
      } else {
        await supabase
          .from('system_config')
          .upsert({ id: 1, trading_mode: targetMode, updated_at: new Date().toISOString() });
      }
      setLocalMode(targetMode);
    } catch (err) {
      console.error('Falha ao alternar modo de trading:', err);
    } finally {
      setIsSwitching(false);
    }
  };

  const handleToggleClick = () => {
    if (currentMode === 'DEMO') {
      setShowConfirmRealModal(true);
    } else {
      performModeChange('DEMO');
    }
  };

  const isRedFlag = Boolean(marketContext?.red_flag_pause_trading);
  const keyDriver = marketContext?.key_driver || 'Telemetria global do News Desk em monitoramento...';
  const lastTrade = trades[0];

  const getAgentDot = (state: string) => {
    switch (state) {
      case 'EXECUTING':
        return 'bg-emerald-400 shadow-[0_0_8px_#10b981] animate-ping';
      case 'ANALYZING':
        return 'bg-amber-400 shadow-[0_0_6px_#f59e0b] animate-pulse';
      case 'QUARANTINED':
        return 'bg-rose-500 shadow-[0_0_6px_#ef4444]';
      case 'IN_MEETING':
        return 'bg-purple-400 shadow-[0_0_8px_#a855f7] animate-pulse';
      default:
        return 'bg-blue-400';
    }
  };

  return (
    <div className="absolute inset-0 pointer-events-none select-none z-40">
      {/* ========================================================= */}
      {/* CABEÇALHO SUPERIOR (HEADER REESTRUTURADO & RESPONSIVO)     */}
      {/* ========================================================= */}
      <Header
        isRedFlag={isRedFlag}
        time={time}
        currentMode={currentMode}
        isSwitching={isSwitching}
        onToggleModeClick={handleToggleClick}
        onOpenMT5Modal={onOpenMT5Modal}
        isConnected={isConnected}
        onOpenSimulation={onOpenSimulation}
        onTriggerMeeting={onTriggerMeeting}
        onTriggerReset={onTriggerReset}
        onTestNewsDelivery={onTestNewsDelivery}
        onTestAuditDelivery={onTestAuditDelivery}
        onTestCalibration={onTestCalibration}
        onTestCRODirective={onTestCRODirective}
        isMeetingActive={isMeetingActive}
      />

      {/* ========================================================= */}
      {/* MODAL DE CONFIRMAÇÃO VERMELHO (RISCO REAL)                */}
      {/* ========================================================= */}
      {showConfirmRealModal && (
        <div className="fixed inset-0 z-[999999] flex items-center justify-center p-4 bg-slate-950/90 backdrop-blur-md pointer-events-auto animate-in fade-in duration-150">
          <div className="w-full max-w-md bg-slate-950 border-2 border-rose-500 rounded-3xl p-6 shadow-[0_0_50px_rgba(244,63,94,0.45)] flex flex-col font-mono text-slate-100 overflow-hidden relative">
            {/* Header Icon + Title */}
            <div className="flex items-center gap-3 mb-3">
              <div className="w-11 h-11 rounded-2xl bg-rose-500/20 border border-rose-500/60 flex items-center justify-center text-rose-400 shadow-[0_0_20px_rgba(244,63,94,0.5)]">
                <AlertTriangle className="w-6 h-6 animate-pulse text-rose-400" />
              </div>
              <div>
                <h3 className="text-base font-black text-rose-400 tracking-wider">
                  ATIVAÇÃO DE RISCO REAL
                </h3>
                <span className="text-[11px] text-rose-300/80">
                  Ambiente de Produção (Conta Real MT5)
                </span>
              </div>
            </div>

            {/* Exact Warning Notice */}
            <div className="my-4 p-4 rounded-2xl bg-rose-950/50 border border-rose-500/40 text-rose-100 text-sm leading-relaxed">
              <p className="font-bold text-rose-200 mb-2">
                &ldquo;Atenção: Você está prestes a ativar o risco financeiro real. Os agentes farão operações com dinheiro de verdade. Confirmar?&rdquo;
              </p>
              <p className="text-[11px] text-rose-300/80 font-sans">
                As ordens disparadas pelos 5 operadores autônomos entrarão diretamente na conta real de execução. Operadores sob quarentena permanecerão isolados na conta DEMO (Shadow Trading).
              </p>
            </div>

            {/* Action Buttons */}
            <div className="flex items-center justify-end gap-3 mt-2">
              <button
                type="button"
                onClick={() => setShowConfirmRealModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 text-xs font-bold transition cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={isSwitching}
                onClick={() => {
                  setShowConfirmRealModal(false);
                  performModeChange('REAL');
                }}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-rose-600 to-red-600 hover:from-rose-500 hover:to-red-500 text-white text-xs font-black shadow-[0_0_20px_rgba(244,63,94,0.6)] transition cursor-pointer flex items-center gap-1.5"
              >
                <ShieldAlert className="w-4 h-4" />
                <span>{isSwitching ? 'Ativando...' : 'Confirmar & Ativar REAL'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* 2. COMPACT & COLLAPSIBLE LEFT SIDEBAR (W-52)              */}
      {/* ========================================================= */}
      {collapsedLeft ? (
        <button
          onClick={() => setCollapsedLeft(false)}
          className="fixed top-32 md:top-24 left-4 z-40 pointer-events-auto flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-950/85 backdrop-blur-md border border-slate-800/80 text-cyan-400 text-xs font-mono font-bold shadow-lg hover:border-cyan-500 transition cursor-pointer"
          title="Expandir lista de postos"
        >
          <Activity className="w-3.5 h-3.5" />
          <span>Postos ({agents.length || 10})</span>
          <ChevronRight className="w-3.5 h-3.5" />
        </button>
      ) : (
        <div className="fixed top-32 md:top-24 left-4 z-40 pointer-events-auto w-52 max-h-[75vh] flex flex-col rounded-2xl bg-slate-950/85 backdrop-blur-md border border-slate-800/80 p-2.5 shadow-2xl">
          <div className="flex items-center justify-between pb-1.5 mb-1.5 border-b border-slate-800">
            <span className="text-[10px] font-mono font-bold text-cyan-400 flex items-center gap-1">
              <Activity className="w-3 h-3" />
              POSTOS ({agents.length || 10})
            </span>
            <button
              onClick={() => setCollapsedLeft(true)}
              className="p-1 rounded hover:bg-slate-850 text-slate-400 hover:text-slate-200 transition cursor-pointer text-xs font-mono font-bold"
              title="Recolher (<<)"
            >
              &lt;&lt;
            </button>
          </div>

          {/* Agents List */}
          <div className="space-y-1 max-h-[50vh] overflow-y-auto pr-1">
            {agents.map((a) => {
              const state = (a.current_state || 'IDLE').toUpperCase();
              return (
                <div
                  key={a.agent_id}
                  onClick={() => onSelectAgent(a)}
                  className="p-1.5 rounded-lg bg-slate-900/60 hover:bg-slate-850 border border-slate-800/80 hover:border-cyan-500/50 transition cursor-pointer flex items-center justify-between group"
                >
                  <div className="flex items-center gap-1.5 overflow-hidden">
                    <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${getAgentDot(state)}`} />
                    <div className="truncate">
                      <div className="text-[10px] font-bold text-slate-200 group-hover:text-cyan-300 truncate">
                        {a.name.split(' ')[0]} {a.name.split(' ')[1] || ''}
                      </div>
                      <div className="text-[8px] font-mono text-slate-500">
                        S{a.sector} • {state}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-1 flex-shrink-0 ml-1">
                    {((a.total_profit !== undefined && a.total_profit !== null) || (a.pnl !== undefined && a.pnl !== null)) && (
                      <span className={`text-[9px] font-mono font-bold px-1 rounded border ${
                        Number(a.total_profit ?? a.pnl ?? 0) > 0 
                          ? 'text-emerald-400 bg-emerald-950/60 border-emerald-500/40' 
                          : Number(a.total_profit ?? a.pnl ?? 0) < 0
                          ? 'text-rose-400 bg-rose-950/60 border-rose-500/40'
                          : 'text-slate-400 bg-slate-900 border-slate-700/50'
                      }`}>
                        {Number(a.total_profit ?? a.pnl ?? 0) > 0 ? '+' : Number(a.total_profit ?? a.pnl ?? 0) < 0 ? '-' : ''}${Math.abs(Number(a.total_profit ?? a.pnl ?? 0)).toFixed(1)}
                      </span>
                    )}
                    {a.allocation_weight !== undefined && (
                      <span className="text-[9px] font-mono text-amber-400 bg-amber-950/40 px-1 rounded border border-amber-500/30 font-bold">
                        {a.allocation_weight}x
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-2 pt-1.5 border-t border-slate-800/80 text-[8px] font-mono text-slate-500 leading-tight">
            🎮 Clique num agente ou arraste para girar a câmera.
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* 3. SLEEK BOTTOM TICKER (FEED TELEMETRIA)                  */}
      {/* ========================================================= */}
      <footer className="fixed bottom-3 inset-x-3 pointer-events-auto rounded-xl bg-slate-950/85 border border-slate-800/80 px-3 py-1.5 shadow-xl backdrop-blur-md flex items-center justify-between gap-3 text-xs font-mono z-40">
        <div className="flex items-center gap-2 overflow-hidden max-w-3xl">
          <Terminal className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
          <span className="text-cyan-400 font-bold uppercase text-[9px] flex-shrink-0">TELEMETRIA:</span>
          <p className="text-slate-300 truncate text-[10px]">
            "{keyDriver}"
          </p>
        </div>

        {lastTrade && (
          <div className="hidden sm:flex items-center gap-1.5 text-[9px] text-slate-400 bg-slate-900 px-2 py-0.5 rounded-lg border border-slate-800 flex-shrink-0">
            <span className="text-slate-500">ORDEM:</span>
            <span className="font-bold text-cyan-300">{lastTrade.symbol}</span>
            <span className={lastTrade.order_type === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}>
              {lastTrade.order_type}
            </span>
            <span className="text-slate-300">${Number(lastTrade.entry_price).toLocaleString()}</span>
          </div>
        )}
      </footer>
    </div>
  );
};

