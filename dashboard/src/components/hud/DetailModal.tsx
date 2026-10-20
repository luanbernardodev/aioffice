'use client';

import React from 'react';
import { X, Bot, TrendingUp, Radio, History, ShieldAlert, Cpu } from 'lucide-react';
import { AgentStatus, Trade, MarketContext } from '@/types';
import { PerformanceChart } from '../PerformanceChart';
import { LiveOrdersFeed } from '../LiveOrdersFeed';

interface DetailModalProps {
  selectedAgent: AgentStatus | null;
  expandedScreen: 'PERFORMANCE' | 'MACRO' | 'TAPE' | null;
  trades: Trade[];
  agents?: AgentStatus[];
  marketContext: MarketContext | null;
  onClose: () => void;
}

export const DetailModal: React.FC<DetailModalProps> = ({
  selectedAgent,
  expandedScreen,
  trades,
  agents = [],
  marketContext,
  onClose,
}) => {
  if (!selectedAgent && !expandedScreen) return null;

  return (
    <div className="fixed inset-0 z-[99999] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div className="relative w-full max-w-4xl rounded-2xl glass-panel p-6 border border-cyan-500/40 shadow-2xl max-h-[85vh] overflow-y-auto">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
        >
          <X className="w-5 h-5" />
        </button>

        {/* 1. AGENT DETAILS MODAL */}
        {selectedAgent && (
          <div>
            <div className="flex items-center gap-3 pb-4 border-b border-slate-800">
              <div className="p-3 rounded-xl bg-cyan-950/70 border border-cyan-500/40 text-cyan-400">
                <Bot className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-100 flex items-center gap-2">
                  {selectedAgent.name}
                  <span className="text-xs font-mono px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
                    Setor {selectedAgent.sector}
                  </span>
                </h3>
                <p className="text-xs font-mono text-slate-400">
                  ID: {selectedAgent.agent_id} • Estilo: {selectedAgent.strategy_style || 'Operações Quantitativas'}
                </p>
              </div>
            </div>

            {/* Metrics & State */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 my-4">
              <div className="p-3 rounded-xl bg-slate-900 border border-slate-800">
                <span className="text-[10px] font-mono text-slate-400 block">ESTADO ATUAL</span>
                <span className="text-sm font-bold font-mono text-cyan-300 mt-1 block">
                  {selectedAgent.current_state}
                </span>
              </div>
              <div className="p-3 rounded-xl bg-slate-900 border border-slate-800">
                <span className="text-[10px] font-mono text-slate-400 block">PESO DE ALOCAÇÃO</span>
                <span className="text-sm font-bold font-mono text-yellow-400 mt-1 block">
                  {selectedAgent.allocation_weight}x
                </span>
              </div>
              <div className="p-3 rounded-xl bg-slate-900 border border-slate-800">
                <span className="text-[10px] font-mono text-slate-400 block">ÚLTIMA ATUALIZAÇÃO</span>
                <span className="text-xs font-mono text-slate-300 mt-1 block">
                  {selectedAgent.updated_at ? new Date(selectedAgent.updated_at).toLocaleTimeString() : 'Ao vivo'}
                </span>
              </div>
            </div>

            {/* Last Thought Bubble Expanded */}
            <div className="p-4 rounded-xl bg-slate-950/80 border border-cyan-500/30 my-4">
              <span className="text-[10px] font-mono uppercase tracking-wider text-cyan-400 font-bold block mb-1">
                ÚLTIMO PENSAMENTO / ANÁLISE NEURAL (LAST THOUGHT):
              </span>
              <p className="text-sm font-sans text-slate-200 leading-relaxed italic">
                "{selectedAgent.last_thought || 'Aguardando telemetria...'}"
              </p>
            </div>
          </div>
        )}

        {/* 2. EXPANDED SCREEN 1: PERFORMANCE */}
        {expandedScreen === 'PERFORMANCE' && (
          <div>
            <div className="flex items-center gap-2 pb-3 mb-4 border-b border-slate-800">
              <TrendingUp className="w-5 h-5 text-blue-400" />
              <h3 className="text-base font-bold text-slate-100">
                CURVA DE PERFORMANCE COMPARATIVA EM DETALHES
              </h3>
            </div>
            <PerformanceChart trades={trades} agents={agents} />
          </div>
        )}

        {/* 3. EXPANDED SCREEN 2: MACRO */}
        {expandedScreen === 'MACRO' && (
          <div>
            <div className="flex items-center gap-2 pb-3 mb-4 border-b border-slate-800">
              <Radio className="w-5 h-5 text-amber-400" />
              <h3 className="text-base font-bold text-slate-100">
                RADAR MACRO & NOTÍCIAS GLOBAIS
              </h3>
            </div>
            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-4 font-mono">
              <div className="flex justify-between items-center text-sm">
                <span>Sentimento Cripto:</span>
                <span className="font-bold text-amber-400">{marketContext?.crypto_sentiment} / 10</span>
              </div>
              <div className="flex justify-between items-center text-sm">
                <span>Sentimento Ouro (XAU):</span>
                <span className="font-bold text-yellow-400">{marketContext?.gold_sentiment} / 10</span>
              </div>
              <div className="flex justify-between items-center text-sm">
                <span>Red Flag Trading Pause:</span>
                <span className={marketContext?.red_flag_pause_trading ? 'text-rose-400 font-bold' : 'text-emerald-400 font-bold'}>
                  {marketContext?.red_flag_pause_trading ? 'ATIVADO (PAUSA)' : 'DESATIVADO (NORMAL)'}
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs">
                <span className="text-cyan-400 font-bold block mb-1">Driver Dominante:</span>
                <p className="text-slate-200">{marketContext?.key_driver}</p>
              </div>
            </div>
          </div>
        )}

        {/* 4. EXPANDED SCREEN 3: TAPE */}
        {expandedScreen === 'TAPE' && (
          <div>
            <div className="flex items-center gap-2 pb-3 mb-4 border-b border-slate-800">
              <History className="w-5 h-5 text-emerald-400" />
              <h3 className="text-base font-bold text-slate-100">
                HISTÓRICO COMPLETO DE OPERAÇÕES
              </h3>
            </div>
            <LiveOrdersFeed trades={trades} />
          </div>
        )}

        {/* Footer */}
        <div className="mt-4 pt-3 border-t border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-200 text-xs font-mono border border-slate-700 transition"
          >
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
};
