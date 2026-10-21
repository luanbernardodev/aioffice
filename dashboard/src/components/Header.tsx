'use client';

import React, { useState, useRef, useEffect } from 'react';
import {
  Zap,
  Clock,
  ChevronDown,
  AlertTriangle,
  FlaskConical,
  ShieldAlert,
  SlidersHorizontal,
} from 'lucide-react';
import { AssetSelector } from '@/components/AssetSelector';

export interface HeaderProps {
  isRedFlag?: boolean;
  time?: string;
  currentMode: 'DEMO' | 'REAL';
  isSwitching?: boolean;
  onToggleModeClick: () => void;
  onOpenMT5Modal?: () => void;
  isConnected?: boolean;
  onOpenSimulation?: () => void;
  onTriggerMeeting?: () => void;
  onTriggerReset?: () => void;
  onTestNewsDelivery?: () => void;
  onTestAuditDelivery?: () => void;
  onTestCalibration?: () => void;
  onTestCRODirective?: () => void;
  isMeetingActive?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  isRedFlag = false,
  time,
  currentMode,
  isSwitching = false,
  onToggleModeClick,
  onOpenMT5Modal,
  isConnected = false,
  onOpenSimulation,
  onTriggerMeeting,
  onTriggerReset,
  onTestNewsDelivery,
  onTestAuditDelivery,
  onTestCalibration,
  onTestCRODirective,
  isMeetingActive = false,
}) => {
  const [showActions, setShowActions] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Fecha o dropdown se clicar fora
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowActions(false);
      }
    };
    if (showActions) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showActions]);

  return (
    <header className="w-full flex flex-col md:flex-row flex-wrap items-center justify-between gap-4 p-4 bg-[#0B101E]/80 backdrop-blur-md border-b border-gray-800 pointer-events-auto select-none z-50 relative">
      {/* ========================================================= */}
      {/* GRUPO ESQUERDO: Identidade e Telemetria de Sistema        */}
      {/* ========================================================= */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Logotipo / "Quant Office" */}
        <div className="flex items-center gap-1.5 font-black text-cyan-300 font-mono text-sm tracking-wider">
          <Zap className="w-4 h-4 text-cyan-400 fill-cyan-400 drop-shadow-[0_0_8px_#00f0ff]" />
          <span>Quant Office</span>
        </div>

        <span className="text-gray-700 hidden sm:inline">|</span>

        {/* Status (Normal / Red Flag) */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-900/60 border border-slate-800 text-xs font-mono">
          <div
            className={`w-2 h-2 rounded-full ${
              isRedFlag ? 'bg-rose-500 animate-ping' : 'bg-emerald-400 animate-pulse'
            }`}
          />
          <span className={isRedFlag ? 'text-rose-400 font-bold' : 'text-emerald-400 font-bold'}>
            {isRedFlag ? 'Red Flag' : 'Normal'}
          </span>
        </div>

        <span className="text-gray-700 hidden sm:inline">|</span>

        {/* Relógio (UTC) */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-900/60 border border-slate-800 text-[11px] font-mono text-slate-300">
          <Clock className="w-3.5 h-3.5 text-cyan-400" />
          <span>{time || '--:-- UTC'}</span>
        </div>
      </div>

      {/* ========================================================= */}
      {/* GRUPO CENTRAL: Painel de Controle de Risco e Ativos       */}
      {/* ========================================================= */}
      <div className="flex items-center gap-3 bg-slate-800/50 rounded-lg p-2 flex-wrap justify-center border border-slate-700/40 shadow-inner">
        {/* Toggle de "DEMO / REAL" */}
        <button
          type="button"
          onClick={onToggleModeClick}
          disabled={isSwitching}
          className={`relative flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold transition-all duration-300 cursor-pointer ${
            currentMode === 'REAL'
              ? 'bg-rose-950/90 text-rose-200 border border-rose-500/80 shadow-[0_0_20px_rgba(244,63,94,0.6)] animate-pulse'
              : 'bg-emerald-950/80 text-emerald-300 border border-emerald-500/60 shadow-[0_0_14px_rgba(16,185,129,0.4)]'
          }`}
          title={
            currentMode === 'REAL'
              ? 'Risco Financeiro Ativo (Clique para mudar para DEMO)'
              : 'Modo Demonstração (Clique para ativar Risco Real)'
          }
        >
          {/* Glow Dot */}
          <span
            className={`w-2 h-2 rounded-full ${
              currentMode === 'REAL'
                ? 'bg-rose-500 shadow-[0_0_8px_#f43f5e] animate-ping'
                : 'bg-emerald-400 shadow-[0_0_6px_#10b981]'
            }`}
          />

          <div className="flex items-center gap-1.5">
            {currentMode === 'REAL' ? (
              <>
                <AlertTriangle className="w-3.5 h-3.5 text-rose-400 animate-bounce" />
                <span className="tracking-wider uppercase font-black text-rose-300 text-[11px]">
                  REAL
                </span>
              </>
            ) : (
              <>
                <FlaskConical className="w-3.5 h-3.5 text-emerald-400" />
                <span className="tracking-wider uppercase font-black text-emerald-300 text-[11px]">
                  DEMO
                </span>
              </>
            )}
          </div>

          {/* Micro badge LAB / RISCO */}
          <div
            className={`px-1.5 py-0.2 rounded-full text-[9px] font-black transition-all ${
              currentMode === 'REAL'
                ? 'bg-rose-600 text-white shadow-[0_0_8px_#f43f5e]'
                : 'bg-emerald-600 text-white shadow-[0_0_6px_#10b981]'
            }`}
          >
            {currentMode === 'REAL' ? 'RISCO' : 'LAB'}
          </div>
        </button>

        {/* Separador sutil */}
        <span className="text-slate-600 hidden sm:inline">|</span>

        {/* Painel de "ATIVOS" com os interruptores de BTC, ETH, SOL, XAUUSD */}
        <AssetSelector className="bg-transparent border-0 shadow-none px-0 py-0" />
      </div>

      {/* ========================================================= */}
      {/* GRUPO DIREITO: Ações do Usuário                           */}
      {/* ========================================================= */}
      <div ref={dropdownRef} className="flex items-center gap-3 shrink-0 relative">
        {/* O botão "Carteira XM" */}
        {onOpenMT5Modal && (
          <button
            type="button"
            onClick={onOpenMT5Modal}
            className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/70 hover:bg-cyan-900 border border-cyan-500/50 text-cyan-300 text-xs font-bold font-mono transition hover:scale-105 active:scale-95 cursor-pointer shadow-[0_0_12px_rgba(6,182,212,0.3)]"
            title="Abrir Carteira MT5 & Ordens (XM)"
          >
            <span>💹 Carteira XM</span>
          </button>
        )}

        {/* O menu dropdown "Ações / Simular" */}
        <button
          type="button"
          onClick={() => setShowActions((prev) => !prev)}
          className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800/90 hover:bg-slate-750 text-slate-200 text-xs font-bold font-mono transition cursor-pointer border border-slate-700 hover:border-cyan-500/60 shadow-sm"
        >
          <span>🛠️ Ações / Simular</span>
          <ChevronDown
            className={`w-3.5 h-3.5 transition-transform duration-200 ${
              showActions ? 'rotate-180' : ''
            }`}
          />
        </button>

        {/* Menu Popover Dropdown */}
        {showActions && (
          <div className="absolute right-0 top-full mt-2 bg-slate-950/95 backdrop-blur-xl border border-slate-800 rounded-2xl p-2.5 shadow-2xl flex flex-col gap-1.5 w-60 z-[9999] animate-in fade-in slide-in-from-top-2 duration-150">
            <div className="text-[10px] font-mono text-slate-400 uppercase tracking-wider px-1 pb-1 border-b border-slate-800/80 flex items-center justify-between">
              <span>Painel de Testes</span>
              <span
                className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-rose-500'}`}
                title={isConnected ? 'Realtime Conectado' : 'Desconectado'}
              />
            </div>

            {/* Direct XM MT5 Wallet Modal */}
            {onOpenMT5Modal && (
              <button
                type="button"
                onClick={() => {
                  onOpenMT5Modal();
                  setShowActions(false);
                }}
                className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-cyan-950/60 hover:bg-cyan-900/80 border border-cyan-500/50 text-cyan-200 text-xs font-mono font-bold transition cursor-pointer text-left"
              >
                <span>💹 Carteira MT5 (XM)</span>
                <span className="text-[9px] text-cyan-400 font-normal">Raio-X TP/SL</span>
              </button>
            )}

            {/* Simular Notícia */}
            {onTestNewsDelivery && (
              <button
                type="button"
                onClick={() => {
                  onTestNewsDelivery();
                  setShowActions(false);
                }}
                className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-amber-950/40 hover:bg-amber-900/60 border border-amber-500/40 text-amber-300 text-xs font-mono font-bold transition cursor-pointer text-left"
              >
                <span>📰 Simular Notícia</span>
                <span className="text-[9px] text-amber-400/70 font-normal">Dominó S2→S3→S1</span>
              </button>
            )}

            {/* Auditoria (S3 -> S4) */}
            {onTestAuditDelivery && (
              <button
                type="button"
                onClick={() => {
                  onTestAuditDelivery();
                  setShowActions(false);
                }}
                className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-500/40 text-emerald-300 text-xs font-mono font-bold transition cursor-pointer text-left"
              >
                <span>📊 Auditoria (S3 → S4)</span>
                <span className="text-[9px] text-emerald-400/70 font-normal">Analytics</span>
              </button>
            )}

            {/* P&D Stops (S4 -> S1) */}
            {onTestCalibration && (
              <button
                type="button"
                onClick={() => {
                  onTestCalibration();
                  setShowActions(false);
                }}
                className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-fuchsia-950/40 hover:bg-fuchsia-900/60 border border-fuchsia-500/40 text-fuchsia-300 text-xs font-mono font-bold transition cursor-pointer text-left"
              >
                <span>🛠️ P&D Stops (S4 → S1)</span>
                <span className="text-[9px] text-fuchsia-400/70 font-normal">P&D Quant</span>
              </button>
            )}

            {/* Diretoria (S5 -> S1) */}
            {onTestCRODirective && (
              <button
                type="button"
                onClick={() => {
                  onTestCRODirective();
                  setShowActions(false);
                }}
                className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-yellow-950/40 hover:bg-yellow-900/60 border border-yellow-500/40 text-yellow-300 text-xs font-mono font-bold transition cursor-pointer text-left"
              >
                <span>🛡️ Diretoria (S5 → S1)</span>
                <span className="text-[9px] text-yellow-400/70 font-normal">Risco CRO</span>
              </button>
            )}

            {/* Reunião Geral */}
            {onTriggerMeeting && (
              <button
                type="button"
                onClick={() => {
                  onTriggerMeeting();
                  setShowActions(false);
                }}
                className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs font-mono font-bold transition border cursor-pointer text-left ${
                  isMeetingActive
                    ? 'bg-purple-900/70 border-purple-400 text-purple-200'
                    : 'bg-purple-950/40 hover:bg-purple-900/60 border-purple-500/40 text-purple-300'
                }`}
              >
                <span>🚨 Reunião Geral</span>
                <span className="text-[9px] text-purple-400/70 font-normal">
                  {isMeetingActive ? 'Ativo' : 'Sala 6'}
                </span>
              </button>
            )}

            {/* Reset Voltar às Mesas */}
            {onTriggerReset && (
              <button
                type="button"
                onClick={() => {
                  onTriggerReset();
                  setShowActions(false);
                }}
                className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700/80 text-slate-300 text-xs font-mono transition cursor-pointer text-left"
              >
                <span>🔄 Voltar às Mesas</span>
                <span className="text-[9px] text-slate-500 font-normal">Reset</span>
              </button>
            )}

            {/* Simulation Launcher */}
            {onOpenSimulation && (
              <button
                type="button"
                onClick={() => {
                  onOpenSimulation();
                  setShowActions(false);
                }}
                className="flex items-center justify-center gap-1.5 mt-1 px-3 py-2 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white text-xs font-bold font-mono shadow-[0_0_12px_rgba(6,182,212,0.4)] border border-cyan-400/50 transition cursor-pointer"
              >
                <SlidersHorizontal className="w-3.5 h-3.5" />
                <span>Abrir Simulador</span>
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
};

export default Header;
