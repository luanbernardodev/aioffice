'use client';

import React from 'react';
import { 
  Building2, 
  Monitor, 
  Radio, 
  Database, 
  ShieldCheck, 
  Users, 
  Flame, 
  Terminal,
  Activity,
  Layers,
  Sparkles,
  Wifi
} from 'lucide-react';
import { AgentStatus } from '@/types';
import { AgentAvatar } from './AgentAvatar';

interface VirtualOfficeProps {
  agents: AgentStatus[];
}

export const VirtualOffice: React.FC<VirtualOfficeProps> = ({ agents }) => {
  // Helper to find agent by ID or fallback
  const getAgent = (id: string, defaultName: string, sector: number): AgentStatus => {
    const found = agents.find(
      (a) => a.agent_id === id || 
             (id === 'news_macro' && a.agent_id === 'news_desk') ||
             (id === 'auditor_quant' && a.agent_id === 'analytics') ||
             (id === 'rnd_engineer' && a.agent_id === 'rnd') ||
             (id === 'cro_manager' && a.agent_id === 'manager')
    );
    if (found) return found;

    return {
      agent_id: id,
      name: defaultName,
      sector,
      current_state: 'IDLE',
      last_thought: 'Aguardando sincronização do feed...',
      allocation_weight: 1.0,
    };
  };

  const opsAlpha = getAgent('ops_alpha', 'Ops Alpha (Trend)', 1);
  const opsBeta = getAgent('ops_beta', 'Ops Beta (Sniper)', 1);
  const opsGamma = getAgent('ops_gamma', 'Ops Gamma (Breakout)', 1);
  const newsMacro = getAgent('news_macro', 'News Desk (Macro)', 2);
  const auditorQuant = getAgent('auditor_quant', 'Auditor Quant', 3);
  const rndEngineer = getAgent('rnd_engineer', 'Engenheiro P&D', 4);
  const croManager = getAgent('cro_manager', 'Diretor de Risco (CRO)', 5);

  const allTrackedAgents = [opsAlpha, opsBeta, opsGamma, newsMacro, auditorQuant, rndEngineer, croManager];
  const agentsInMeeting = allTrackedAgents.filter((a) => (a.current_state || '').toUpperCase() === 'IN_MEETING');
  const isCrisisSession = agentsInMeeting.length > 0;

  return (
    <div className="relative rounded-2xl glass-panel p-4 overflow-hidden border border-cyan-500/20 shadow-2xl">
      {/* Background Cyber Grid & Floorplan Texture */}
      <div className="absolute inset-0 cyber-grid opacity-30 pointer-events-none" />
      <div className="absolute -top-24 -left-24 w-96 h-96 bg-cyan-500/5 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-24 -right-24 w-96 h-96 bg-purple-500/5 rounded-full blur-3xl pointer-events-none" />

      {/* Header Banner */}
      <div className="relative z-10 flex items-center justify-between pb-3 mb-4 border-b border-slate-800">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-cyan-950/60 border border-cyan-500/40 text-cyan-400">
            <Building2 className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-slate-100 tracking-wide">
                ESCRITÓRIO VIRTUAL 2D — PLANTA BAIXA OPERACIONAL
              </h2>
              <span className="flex items-center gap-1 text-[10px] font-mono text-cyan-400 bg-cyan-950/40 px-2 py-0.5 rounded border border-cyan-500/30">
                <Wifi className="w-3 h-3 text-cyan-400 animate-pulse" />
                6 SETORES ATIVOS
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Ambiente imersivo com telemetria neural, monitoramento de postos e reunião de emergência
            </p>
          </div>
        </div>

        {/* Global Meeting Status Alert */}
        {isCrisisSession && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-purple-950/80 border border-purple-500/60 shadow-[0_0_15px_#a855f7] animate-pulse">
            <Flame className="w-4 h-4 text-purple-400 animate-bounce" />
            <span className="text-xs font-bold text-purple-200 tracking-wider">
              ⚠️ SESSÃO DE CRISE NO BOARDROOM ({agentsInMeeting.length} AGENTES)
            </span>
          </div>
        )}
      </div>

      {/* 2D Floorplan Grid Layout */}
      <div className="relative z-10 grid grid-cols-1 lg:grid-cols-12 gap-4">
        
        {/* ========================================================= */}
        {/* SETOR 1: MESA DE OPERAÇÕES (TRADING DESK) - Col 7 */}
        {/* ========================================================= */}
        <div className="lg:col-span-7 rounded-xl bg-slate-900/60 border border-blue-500/30 p-3.5 relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between mb-3 border-b border-slate-800/80 pb-2">
            <div className="flex items-center gap-2 text-blue-400 font-mono text-xs font-semibold">
              <Monitor className="w-4 h-4 text-blue-400" />
              <span>SETOR 1: MESA DE OPERAÇÕES (TRADING DESK)</span>
            </div>
            <span className="text-[10px] font-mono text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded">
              Multi-Monitores & Execução Ultra-Rápida
            </span>
          </div>

          {/* Desks Stations with Multi-Monitors */}
          <div className="grid grid-cols-3 gap-2">
            
            {/* Ops Alpha Station */}
            <div className="relative flex flex-col items-center p-2 rounded-lg bg-slate-950/70 border border-slate-800/90 group hover:border-blue-500/50 transition-all">
              {/* Multi-monitor visuals above desk */}
              <div className="w-full flex items-center justify-center gap-1 mb-2 opacity-80">
                <div className="w-5 h-3.5 bg-blue-950 border border-blue-500/50 rounded-sm flex items-center justify-center">
                  <div className="w-3 h-1 bg-blue-400 rounded-full animate-pulse" />
                </div>
                <div className="w-6 h-4 bg-blue-900/80 border border-blue-400 rounded-sm flex items-center justify-center shadow-[0_0_8px_rgba(59,130,246,0.3)]">
                  <span className="text-[6px] font-mono text-blue-200">BTC</span>
                </div>
                <div className="w-5 h-3.5 bg-blue-950 border border-blue-500/50 rounded-sm flex items-center justify-center">
                  <div className="w-3 h-1 bg-cyan-400 rounded-full" />
                </div>
              </div>

              {/* Avatar or Away status */}
              {opsAlpha.current_state === 'IN_MEETING' ? (
                <div className="py-8 flex flex-col items-center justify-center text-center">
                  <div className="w-8 h-8 rounded-full border border-purple-400/50 bg-purple-950/40 flex items-center justify-center text-purple-400 animate-pulse">
                    <Users className="w-4 h-4" />
                  </div>
                  <span className="text-[10px] font-mono text-purple-300 mt-2">Em Reunião</span>
                </div>
              ) : (
                <AgentAvatar agent={opsAlpha} badgeColor="blue" />
              )}
              
              <div className="mt-1 text-[9px] font-mono text-slate-400">Trend / Pullback</div>
            </div>

            {/* Ops Beta Station */}
            <div className="relative flex flex-col items-center p-2 rounded-lg bg-slate-950/70 border border-slate-800/90 group hover:border-purple-500/50 transition-all">
              <div className="w-full flex items-center justify-center gap-1 mb-2 opacity-80">
                <div className="w-5 h-3.5 bg-purple-950 border border-purple-500/50 rounded-sm flex items-center justify-center">
                  <div className="w-3 h-1 bg-purple-400 rounded-full animate-pulse" />
                </div>
                <div className="w-6 h-4 bg-purple-900/80 border border-purple-400 rounded-sm flex items-center justify-center shadow-[0_0_8px_rgba(168,85,247,0.3)]">
                  <span className="text-[6px] font-mono text-purple-200">ETH</span>
                </div>
                <div className="w-5 h-3.5 bg-purple-950 border border-purple-500/50 rounded-sm flex items-center justify-center">
                  <div className="w-3 h-1 bg-pink-400 rounded-full" />
                </div>
              </div>

              {opsBeta.current_state === 'IN_MEETING' ? (
                <div className="py-8 flex flex-col items-center justify-center text-center">
                  <div className="w-8 h-8 rounded-full border border-purple-400/50 bg-purple-950/40 flex items-center justify-center text-purple-400 animate-pulse">
                    <Users className="w-4 h-4" />
                  </div>
                  <span className="text-[10px] font-mono text-purple-300 mt-2">Em Reunião</span>
                </div>
              ) : (
                <AgentAvatar agent={opsBeta} badgeColor="purple" />
              )}

              <div className="mt-1 text-[9px] font-mono text-slate-400">Mean Reversion / Sniper</div>
            </div>

            {/* Ops Gamma Station */}
            <div className="relative flex flex-col items-center p-2 rounded-lg bg-slate-950/70 border border-slate-800/90 group hover:border-emerald-500/50 transition-all">
              <div className="w-full flex items-center justify-center gap-1 mb-2 opacity-80">
                <div className="w-5 h-3.5 bg-emerald-950 border border-emerald-500/50 rounded-sm flex items-center justify-center">
                  <div className="w-3 h-1 bg-emerald-400 rounded-full animate-pulse" />
                </div>
                <div className="w-6 h-4 bg-emerald-900/80 border border-emerald-400 rounded-sm flex items-center justify-center shadow-[0_0_8px_rgba(16,185,129,0.3)]">
                  <span className="text-[6px] font-mono text-emerald-200">GOLD</span>
                </div>
                <div className="w-5 h-3.5 bg-emerald-950 border border-emerald-500/50 rounded-sm flex items-center justify-center">
                  <div className="w-3 h-1 bg-teal-400 rounded-full" />
                </div>
              </div>

              {opsGamma.current_state === 'IN_MEETING' ? (
                <div className="py-8 flex flex-col items-center justify-center text-center">
                  <div className="w-8 h-8 rounded-full border border-purple-400/50 bg-purple-950/40 flex items-center justify-center text-purple-400 animate-pulse">
                    <Users className="w-4 h-4" />
                  </div>
                  <span className="text-[10px] font-mono text-purple-300 mt-2">Em Reunião</span>
                </div>
              ) : (
                <AgentAvatar agent={opsGamma} badgeColor="emerald" />
              )}

              <div className="mt-1 text-[9px] font-mono text-slate-400">Volatility Breakout</div>
            </div>

          </div>
        </div>

        {/* ========================================================= */}
        {/* SETOR 2: ESTAÇÃO DE INTELIGÊNCIA & NOTÍCIAS - Col 5 */}
        {/* ========================================================= */}
        <div className="lg:col-span-5 rounded-xl bg-slate-900/60 border border-amber-500/30 p-3.5 relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between mb-3 border-b border-slate-800/80 pb-2">
            <div className="flex items-center gap-2 text-amber-400 font-mono text-xs font-semibold">
              <Radio className="w-4 h-4 text-amber-400" />
              <span>SETOR 2: ESTAÇÃO DE INTELIGÊNCIA (NEWS DESK)</span>
            </div>
            <div className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
          </div>

          <div className="flex items-center justify-around gap-2">
            {/* Terminal Antenna Animation */}
            <div className="hidden sm:flex flex-col items-center justify-center p-3 rounded-lg bg-slate-950/80 border border-amber-500/20 text-center">
              <div className="relative w-12 h-12 flex items-center justify-center">
                <div className="absolute inset-0 rounded-full border border-amber-500/30 radar-sweep" />
                <Radio className="w-6 h-6 text-amber-400 animate-pulse" />
              </div>
              <span className="text-[9px] font-mono text-amber-300/80 mt-1">Radar Macro</span>
              <span className="text-[8px] font-mono text-slate-500">Reuters • Bloomberg</span>
            </div>

            {/* Avatar */}
            {newsMacro.current_state === 'IN_MEETING' ? (
              <div className="py-6 flex flex-col items-center justify-center text-center">
                <div className="w-8 h-8 rounded-full border border-purple-400/50 bg-purple-950/40 flex items-center justify-center text-purple-400 animate-pulse">
                  <Users className="w-4 h-4" />
                </div>
                <span className="text-[10px] font-mono text-purple-300 mt-2">Em Reunião no Boardroom</span>
              </div>
            ) : (
              <AgentAvatar agent={newsMacro} badgeColor="amber" />
            )}
          </div>
        </div>

        {/* ========================================================= */}
        {/* SETOR 6: SALA DE REUNIÃO DE CRISE (BOARDROOM) - Col 6 (Central) */}
        {/* ========================================================= */}
        <div className={`lg:col-span-6 rounded-xl border p-3.5 relative overflow-hidden transition-all duration-500 ${
          isCrisisSession 
            ? 'bg-purple-950/30 border-purple-500/60 shadow-[0_0_30px_rgba(168,85,247,0.25)]' 
            : 'bg-slate-900/50 border-purple-500/20'
        }`}>
          <div className="flex items-center justify-between mb-3 border-b border-slate-800/80 pb-2">
            <div className="flex items-center gap-2 text-purple-400 font-mono text-xs font-semibold">
              <Users className="w-4 h-4 text-purple-400" />
              <span>SETOR 6: SALA DE REUNIÃO DE CRISE (BOARDROOM)</span>
            </div>
            <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${
              isCrisisSession 
                ? 'bg-purple-500/30 text-purple-200 border border-purple-400 font-bold' 
                : 'bg-slate-800 text-slate-400'
            }`}>
              {isCrisisSession ? 'CONSELHO ATIVO' : 'MESA EM ESPERA'}
            </span>
          </div>

          {/* Central Round Conference Table */}
          <div className="relative min-h-[190px] flex items-center justify-center">
            {/* The Physical Round Table */}
            <div className={`w-48 h-32 rounded-[50%] border-2 flex flex-col items-center justify-center transition-all duration-500 ${
              isCrisisSession 
                ? 'bg-purple-950/80 border-purple-400 shadow-[0_0_25px_rgba(168,85,247,0.5)]' 
                : 'bg-slate-950/90 border-slate-800'
            }`}>
              <div className="text-center p-2">
                <div className="text-[10px] font-mono font-bold text-purple-300">
                  MESA DIRETIVA
                </div>
                <div className="text-[8px] font-mono text-slate-400 mt-0.5">
                  {isCrisisSession ? 'Conselho em Deliberação' : 'Todos os operadores nos postos'}
                </div>
              </div>
            </div>

            {/* Holographic Projector Beam in the middle */}
            {isCrisisSession && (
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-16 h-16 rounded-full bg-purple-500/20 blur-md pointer-events-none animate-pulse" />
            )}

            {/* Seated Avatars around the round table when in IN_MEETING */}
            <div className="absolute inset-0 flex flex-wrap items-center justify-around p-2 pointer-events-auto">
              {agentsInMeeting.length > 0 ? (
                agentsInMeeting.map((meetingAgent) => (
                  <div key={meetingAgent.agent_id} className="scale-90 transform transition-all duration-500">
                    <AgentAvatar agent={meetingAgent} isMeetingMode={true} />
                  </div>
                ))
              ) : (
                <div className="text-center text-xs text-slate-500 font-mono italic">
                  Nenhum agente em reunião no momento. (Mesa redonda livre)
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ========================================================= */}
        {/* SETOR 3 & 4: LABORATÓRIO QUANT (ANÁLISE & P&D) - Col 3 */}
        {/* ========================================================= */}
        <div className="lg:col-span-3 rounded-xl bg-slate-900/60 border border-cyan-500/30 p-3.5 relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between mb-3 border-b border-slate-800/80 pb-2">
            <div className="flex items-center gap-1.5 text-cyan-400 font-mono text-xs font-semibold">
              <Database className="w-4 h-4 text-cyan-400" />
              <span>SETOR 3 & 4: LAB QUANT & P&D</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {/* Auditor Quant */}
            {auditorQuant.current_state === 'IN_MEETING' ? (
              <div className="py-6 flex flex-col items-center justify-center text-center">
                <div className="w-7 h-7 rounded-full border border-purple-400/50 bg-purple-950/40 flex items-center justify-center text-purple-400 animate-pulse">
                  <Users className="w-3.5 h-3.5" />
                </div>
                <span className="text-[9px] font-mono text-purple-300 mt-1">No Boardroom</span>
              </div>
            ) : (
              <AgentAvatar agent={auditorQuant} badgeColor="cyan" />
            )}

            {/* R&D Engineer */}
            {rndEngineer.current_state === 'IN_MEETING' ? (
              <div className="py-6 flex flex-col items-center justify-center text-center">
                <div className="w-7 h-7 rounded-full border border-purple-400/50 bg-purple-950/40 flex items-center justify-center text-purple-400 animate-pulse">
                  <Users className="w-3.5 h-3.5" />
                </div>
                <span className="text-[9px] font-mono text-purple-300 mt-1">No Boardroom</span>
              </div>
            ) : (
              <AgentAvatar agent={rndEngineer} badgeColor="fuchsia" />
            )}
          </div>

          {/* Supercomputer Rack LEDs */}
          <div className="mt-3 p-1.5 rounded bg-slate-950 border border-cyan-500/20 flex items-center justify-between">
            <span className="text-[8px] font-mono text-slate-400">CLUSTER COMPUTAÇÃO</span>
            <div className="flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <div className="w-1.5 h-1.5 rounded-full bg-fuchsia-400 animate-pulse" />
            </div>
          </div>
        </div>

        {/* ========================================================= */}
        {/* SETOR 5: SALA DA DIRETORIA (CRO - CHIEF RISK OFFICER) - Col 3 */}
        {/* ========================================================= */}
        <div className="lg:col-span-3 rounded-xl bg-slate-900/60 border border-emerald-500/30 p-3.5 relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between mb-3 border-b border-slate-800/80 pb-2">
            <div className="flex items-center gap-1.5 text-emerald-400 font-mono text-xs font-semibold">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span>SETOR 5: DIRETORIA (CRO)</span>
            </div>
          </div>

          <div className="flex flex-col items-center justify-center">
            {croManager.current_state === 'IN_MEETING' ? (
              <div className="py-6 flex flex-col items-center justify-center text-center">
                <div className="w-7 h-7 rounded-full border border-purple-400/50 bg-purple-950/40 flex items-center justify-center text-purple-400 animate-pulse">
                  <Users className="w-3.5 h-3.5" />
                </div>
                <span className="text-[9px] font-mono text-purple-300 mt-1">Conduzindo Boardroom</span>
              </div>
            ) : (
              <AgentAvatar agent={croManager} badgeColor="emerald" />
            )}
          </div>

          {/* Hands Allocation Weight Gauge */}
          <div className="mt-2 p-2 rounded-lg bg-slate-950/90 border border-slate-800 text-[10px] font-mono">
            <div className="text-slate-400 mb-1 flex items-center justify-between text-[9px]">
              <span>PESO DA MÃO (CRO):</span>
              <span className="text-amber-400 font-bold">ALOCAÇÃO</span>
            </div>
            <div className="space-y-1">
              <div className="flex justify-between items-center text-[9px]">
                <span className="text-blue-400">Alpha:</span>
                <span className="text-slate-200 font-bold">{opsAlpha.allocation_weight}x</span>
              </div>
              <div className="flex justify-between items-center text-[9px]">
                <span className="text-purple-400">Beta:</span>
                <span className={opsBeta.allocation_weight === 0 ? 'text-rose-400 font-bold' : 'text-slate-200 font-bold'}>
                  {opsBeta.allocation_weight === 0 ? '0.0x (Quarentena)' : `${opsBeta.allocation_weight}x`}
                </span>
              </div>
              <div className="flex justify-between items-center text-[9px]">
                <span className="text-emerald-400">Gamma:</span>
                <span className="text-slate-200 font-bold">{opsGamma.allocation_weight}x</span>
              </div>
            </div>
          </div>

        </div>

      </div>
    </div>
  );
};
