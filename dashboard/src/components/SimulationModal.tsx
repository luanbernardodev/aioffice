'use client';

import React, { useState } from 'react';
import { 
  X, 
  Zap, 
  Users, 
  Lock, 
  Cpu, 
  RotateCcw, 
  AlertTriangle,
  Check,
  Loader2
} from 'lucide-react';

interface SimulationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onActionTriggered?: (action: string) => void;
}

export const SimulationModal: React.FC<SimulationModalProps> = ({ isOpen, onClose, onActionTriggered }) => {
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ message: string; isError?: boolean } | null>(null);

  if (!isOpen) return null;

  const triggerSimulation = async (action: string) => {
    setLoadingAction(action);
    setFeedback(null);
    if (onActionTriggered) onActionTriggered(action);
    try {
      const res = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Falha ao executar simulação');

      setFeedback({ message: data.message || 'Comando enviado com sucesso!' });
      setTimeout(() => setFeedback(null), 4000);
    } catch (err: any) {
      setFeedback({ message: err.message || 'Erro inesperado', isError: true });
    } finally {
      setLoadingAction(null);
    }
  };

  const simulationOptions = [
    {
      id: 'DOMINO_NEWS',
      title: 'Simular Notícia (Efeito Dominó S2 → S3 → S1)',
      desc: 'Dispara a coreografia completa: News Macro vai ao S3, Auditor Quant vai à Sala 1 contornando a Sala 6 e libera as ordens.',
      icon: <Zap className="w-5 h-5 text-amber-400" />,
      color: 'hover:border-amber-500/60 hover:bg-amber-950/20',
      badge: 'Coreografia 3D Dominó',
    },
    {
      id: 'ORDER_ALPHA',
      title: 'Disparo de Ordem (Alpha Executing)',
      desc: 'Coloca Ops Alpha em EXECUTING (neon verde pulsante), dispara ordem de trade e gera PnL imediato.',
      icon: <Zap className="w-5 h-5 text-emerald-400" />,
      color: 'hover:border-emerald-500/60 hover:bg-emerald-950/20',
      badge: 'Gatilho de Execução',
    },
    {
      id: 'EMERGENCY_MEETING',
      title: 'Conselho de Crise (Boardroom Meeting)',
      desc: 'Muda o estado dos agentes para IN_MEETING e move seus avatares fisicamente para a mesa redonda central.',
      icon: <Users className="w-5 h-5 text-purple-400" />,
      color: 'hover:border-purple-500/60 hover:bg-purple-950/20',
      badge: 'Animação de Movimento',
    },
    {
      id: 'QUARANTINE_BETA',
      title: 'Quarentena de Risco (Ops Beta)',
      desc: 'Aciona quarentena no Agente Beta (grade laser vermelha, cadeado, suspensão e alocação zerada).',
      icon: <Lock className="w-5 h-5 text-rose-400" />,
      color: 'hover:border-rose-500/60 hover:bg-rose-950/20',
      badge: 'Controle de Risco',
    },
    {
      id: 'MARKET_ANALYSIS',
      title: 'Varredura de Mercado (Analyzing Mode)',
      desc: 'Ativa o modo ANALYZING nos 3 operadores, exibindo aura amarela pulsante e processamento neural.',
      icon: <Cpu className="w-5 h-5 text-amber-400" />,
      color: 'hover:border-amber-500/60 hover:bg-amber-950/20',
      badge: 'Scan Neural',
    },
    {
      id: 'TOGGLE_RED_FLAG',
      title: 'Alternar Red Flag / Macro Pausa',
      desc: 'Inverte o indicador de Red Flag e altera os termômetros de sentimento de Cripto e Ouro no topo.',
      icon: <AlertTriangle className="w-5 h-5 text-yellow-400" />,
      color: 'hover:border-yellow-500/60 hover:bg-yellow-950/20',
      badge: 'Telemetria Macro',
    },
    {
      id: 'RESET_IDLE',
      title: 'Reset para Normal (All Idle)',
      desc: 'Devolve todos os agentes aos seus postos operacionais em estado IDLE com pensamentos calibrados.',
      icon: <RotateCcw className="w-5 h-5 text-cyan-400" />,
      color: 'hover:border-cyan-500/60 hover:bg-cyan-950/20',
      badge: 'Restauração',
    },
  ];

  return (
    <div className="fixed inset-0 z-[99999] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div className="relative w-full max-w-2xl rounded-2xl glass-panel p-6 border border-cyan-500/40 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-cyan-950/70 border border-cyan-500/40 text-cyan-400">
              <Zap className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-100 uppercase tracking-wide">
                CENTRO DE TESTES & SIMULAÇÃO EM TEMPO REAL
              </h2>
              <p className="text-xs text-slate-400">
                Dispare eventos para validar as animações e transições instantâneas do Supabase Realtime
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Feedback message banner */}
        {feedback && (
          <div
            className={`mt-4 p-3 rounded-xl border flex items-center gap-2 text-xs font-mono animate-fadeIn ${
              feedback.isError
                ? 'bg-rose-950/60 border-rose-500/50 text-rose-200'
                : 'bg-emerald-950/60 border-emerald-500/50 text-emerald-200'
            }`}
          >
            {feedback.isError ? <AlertTriangle className="w-4 h-4 text-rose-400" /> : <Check className="w-4 h-4 text-emerald-400" />}
            <span>{feedback.message}</span>
          </div>
        )}

        {/* Action Grid */}
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
          {simulationOptions.map((opt) => {
            const isLoading = loadingAction === opt.id;
            return (
              <button
                key={opt.id}
                onClick={() => triggerSimulation(opt.id)}
                disabled={Boolean(loadingAction)}
                className={`p-3.5 rounded-xl text-left bg-slate-950/80 border border-slate-800/90 transition-all duration-200 cursor-pointer disabled:opacity-50 flex flex-col justify-between ${opt.color}`}
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      {opt.icon}
                      <span className="text-xs font-bold text-slate-100">{opt.title}</span>
                    </div>
                    <span className="text-[9px] font-mono text-cyan-400/80 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                      {opt.badge}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 leading-relaxed font-sans">
                    {opt.desc}
                  </p>
                </div>

                <div className="mt-3 pt-2 border-t border-slate-900 flex items-center justify-between text-[10px] font-mono text-slate-400">
                  <span>Disparar no Supabase</span>
                  {isLoading ? (
                    <Loader2 className="w-3.5 h-3.5 text-cyan-400 animate-spin" />
                  ) : (
                    <span className="text-cyan-400 font-bold">EXEC &gt;</span>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {/* Footer */}
        <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between text-[11px] font-mono text-slate-500">
          <span>Updates acontecem instantaneamente via canais postgres_changes</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-700 font-mono transition"
          >
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
};
