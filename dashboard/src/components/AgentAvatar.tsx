'use client';

import React, { useState } from 'react';
import { 
  Bot, 
  Cpu, 
  TrendingUp, 
  ShieldAlert, 
  Zap, 
  Activity, 
  Lock, 
  Radio, 
  MessageSquare,
  Sparkles
} from 'lucide-react';
import { AgentStatus, AgentState } from '@/types';

interface AgentAvatarProps {
  agent: AgentStatus;
  isMeetingMode?: boolean;
  roleIcon?: React.ReactNode;
  deskLabel?: string;
  badgeColor?: string;
}

export const AgentAvatar: React.FC<AgentAvatarProps> = ({
  agent,
  isMeetingMode = false,
  roleIcon,
  deskLabel,
  badgeColor = 'cyan',
}) => {
  const [showFullThought, setShowFullThought] = useState(false);
  const state = (agent.current_state || 'IDLE').toUpperCase() as AgentState;

  // Visual cues based on state
  let stateClass = 'avatar-idle';
  let ringColor = 'border-blue-500/50 bg-blue-950/40 text-blue-300';
  let stateBadge = {
    label: 'IDLE',
    bg: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    icon: <Activity className="w-3 h-3 text-blue-400 animate-pulse" />,
  };

  if (state === 'ANALYZING') {
    stateClass = 'avatar-analyzing';
    ringColor = 'border-amber-400 bg-amber-950/50 text-amber-300';
    stateBadge = {
      label: 'ANALYZING',
      bg: 'bg-amber-500/20 text-amber-300 border-amber-500/50',
      icon: <Cpu className="w-3 h-3 text-amber-400 animate-spin" />,
    };
  } else if (state === 'EXECUTING') {
    stateClass = 'avatar-executing';
    ringColor = 'border-emerald-400 bg-emerald-950/60 text-emerald-300';
    stateBadge = {
      label: 'EXECUTING',
      bg: 'bg-emerald-500/30 text-emerald-200 border-emerald-400 shadow-lg shadow-emerald-500/20',
      icon: <Zap className="w-3 h-3 text-emerald-300 animate-bounce" />,
    };
  } else if (state === 'QUARANTINED') {
    stateClass = 'avatar-quarantined';
    ringColor = 'border-rose-500 bg-rose-950/70 text-rose-300';
    stateBadge = {
      label: 'QUARANTINED',
      bg: 'bg-rose-500/20 text-rose-300 border-rose-500/60',
      icon: <Lock className="w-3 h-3 text-rose-400" />,
    };
  } else if (state === 'IN_MEETING') {
    stateClass = 'avatar-meeting';
    ringColor = 'border-purple-400 bg-purple-950/60 text-purple-300';
    stateBadge = {
      label: 'IN MEETING',
      bg: 'bg-purple-500/20 text-purple-300 border-purple-500/50',
      icon: <Radio className="w-3 h-3 text-purple-400 animate-pulse" />,
    };
  }

  // Pixel avatar face styling based on agent_id
  const getAvatarVisual = () => {
    switch (agent.agent_id) {
      case 'ops_alpha':
        return (
          <div className="relative">
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-blue-600 to-indigo-900 flex items-center justify-center border border-blue-400/50 shadow-inner">
              <TrendingUp className="w-6 h-6 text-blue-200" />
            </div>
            {/* Operator Visor */}
            <div className="absolute top-3 left-1 right-1 h-2 bg-cyan-400 rounded-sm opacity-90 shadow-[0_0_8px_#00f0ff]" />
          </div>
        );
      case 'ops_beta':
        return (
          <div className="relative">
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-purple-600 to-pink-950 flex items-center justify-center border border-purple-400/50 shadow-inner">
              <Zap className="w-6 h-6 text-purple-200" />
            </div>
            {/* Sniper Eye Visor */}
            <div className="absolute top-2.5 right-2 w-3 h-3 rounded-full bg-red-500 shadow-[0_0_8px_#ef4444] border border-white" />
          </div>
        );
      case 'ops_gamma':
        return (
          <div className="relative">
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-emerald-600 to-teal-950 flex items-center justify-center border border-emerald-400/50 shadow-inner">
              <Sparkles className="w-6 h-6 text-emerald-200" />
            </div>
            {/* Tactical HUD */}
            <div className="absolute top-3 left-1.5 right-1.5 h-1.5 bg-emerald-300 rounded shadow-[0_0_6px_#34d399]" />
          </div>
        );
      case 'news_macro':
      case 'news_desk':
        return (
          <div className="relative">
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-amber-500 to-orange-950 flex items-center justify-center border border-amber-400/50 shadow-inner">
              <Radio className="w-6 h-6 text-amber-200" />
            </div>
            <div className="absolute -top-1.5 -right-1 w-2.5 h-2.5 rounded-full bg-amber-400 animate-ping" />
          </div>
        );
      case 'auditor_quant':
      case 'analytics':
        return (
          <div className="relative">
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-cyan-600 to-blue-950 flex items-center justify-center border border-cyan-400/50 shadow-inner">
              <Cpu className="w-6 h-6 text-cyan-200" />
            </div>
            <div className="absolute top-3 left-2 right-2 h-1.5 bg-cyan-300 rounded shadow-[0_0_6px_#67e8f9]" />
          </div>
        );
      case 'rnd_engineer':
      case 'rnd':
        return (
          <div className="relative">
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-fuchsia-600 to-slate-900 flex items-center justify-center border border-fuchsia-400/50 shadow-inner">
              <Bot className="w-6 h-6 text-fuchsia-200" />
            </div>
            <div className="absolute top-2 left-2 w-2 h-2 rounded-full bg-pink-400 shadow-[0_0_6px_#f472b6]" />
            <div className="absolute top-2 right-2 w-2 h-2 rounded-full bg-pink-400 shadow-[0_0_6px_#f472b6]" />
          </div>
        );
      case 'cro_manager':
      case 'manager':
        return (
          <div className="relative">
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-amber-400 to-yellow-950 flex items-center justify-center border border-amber-300 shadow-inner">
              <ShieldAlert className="w-6 h-6 text-yellow-100" />
            </div>
            {/* Director Gold Collar */}
            <div className="absolute bottom-0 left-2 right-2 h-1 bg-amber-300 rounded shadow-[0_0_8px_#fde047]" />
          </div>
        );
      default:
        return (
          <div className="w-11 h-11 rounded-lg bg-slate-800 flex items-center justify-center border border-slate-700">
            <Bot className="w-6 h-6 text-slate-300" />
          </div>
        );
    }
  };

  const thought = agent.last_thought || 'Aguardando sinais...';
  const truncatedThought = thought.length > 70 ? thought.slice(0, 68) + '...' : thought;

  return (
    <div className="relative flex flex-col items-center group select-none">
      {/* Speech Bubble */}
      <div 
        onClick={() => setShowFullThought(!showFullThought)}
        className="speech-bubble mb-2 px-2.5 py-1.5 max-w-[210px] min-w-[140px] text-center cursor-pointer transition-all duration-300 hover:scale-105 hover:z-50 hover:border-cyan-400 shadow-lg"
      >
        <div className="flex items-center justify-center gap-1 text-[10px] font-mono text-cyan-400 mb-0.5 uppercase tracking-wider">
          <MessageSquare className="w-2.5 h-2.5" />
          <span>{agent.name.split(' ')[0]}</span>
          {agent.allocation_weight !== undefined && (
            <span className="text-amber-400 ml-1">[{agent.allocation_weight}x]</span>
          )}
        </div>
        <p className="text-[11px] leading-tight font-sans text-slate-200">
          {showFullThought ? thought : truncatedThought}
        </p>
      </div>

      {/* Avatar Container with State Glow */}
      <div className={`relative p-1.5 rounded-xl border-2 transition-all duration-300 ${ringColor} ${stateClass}`}>
        {/* Quarantined Laser Grid Overlay */}
        {state === 'QUARANTINED' && (
          <div className="absolute inset-0 bg-red-950/80 rounded-xl z-20 flex flex-col items-center justify-center border border-red-500 shadow-[0_0_15px_#ef4444]">
            <Lock className="w-5 h-5 text-red-400 animate-pulse" />
            <span className="text-[8px] font-bold text-red-200 tracking-tighter uppercase mt-0.5">SUSPENSO</span>
          </div>
        )}

        {/* Avatar Graphic */}
        {getAvatarVisual()}

        {/* State Icon Badge at bottom right of avatar */}
        <div className={`absolute -bottom-1 -right-1 px-1 py-0.5 rounded text-[9px] font-mono font-bold flex items-center gap-0.5 border ${stateBadge.bg}`}>
          {stateBadge.icon}
        </div>
      </div>

      {/* Label and Allocation Weight */}
      <div className="mt-1.5 text-center">
        <div className="text-[11px] font-semibold text-slate-100 flex items-center justify-center gap-1">
          {agent.name}
        </div>
        <div className="flex items-center justify-center gap-1.5 mt-0.5">
          <span className={`text-[9px] px-1.5 py-0.2 rounded border font-mono ${stateBadge.bg}`}>
            {state}
          </span>
          {agent.allocation_weight !== undefined && (
            <span className="text-[9px] text-amber-400 font-mono bg-amber-950/40 px-1 rounded border border-amber-500/30">
              W: {agent.allocation_weight}x
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
