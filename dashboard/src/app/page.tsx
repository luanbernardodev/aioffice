'use client';

import React, { useEffect, useState, useCallback, useRef } from 'react';
import dynamic from 'next/dynamic';
import { supabase } from '@/lib/supabase';
import { AgentStatus, MarketContext, Trade, MT5AccountStatus } from '@/types';
import { useTradingData } from '@/hooks/useTradingData';
import { AgentMission } from '@/components/3d/VoxelAgent';
import { CommandHUD } from '@/components/hud/CommandHUD';
import { DetailModal } from '@/components/hud/DetailModal';
import { MT5AccountPanel } from '@/components/hud/MT5AccountPanel';
import { SimulationModal } from '@/components/SimulationModal';
import { ErrorBoundary } from '@/components/ErrorBoundary';

// Dynamically import Three.js 3D canvas scene with ssr: false
const OfficeScene = dynamic(() => import('@/components/3d/OfficeScene'), {
  ssr: false,
  loading: () => (
    <div className="w-screen h-screen flex flex-col items-center justify-center bg-[#060714] text-cyan-400 font-mono">
      <div className="w-12 h-12 rounded-full border-2 border-cyan-400 border-t-transparent animate-spin mb-4 shadow-[0_0_20px_#00f0ff]" />
      <span className="text-sm font-bold tracking-widest uppercase">
        CARREGANDO PLANTA BAIXA 3D & SALAS SETORIAIS...
      </span>
      <span className="text-xs text-slate-500 mt-1">
        Sincronizando telemetria neural com Supabase Realtime
      </span>
    </div>
  ),
});

export default function DashboardPage() {
  const [agents, setAgents] = useState<AgentStatus[]>([]);
  const [marketContext, setMarketContext] = useState<MarketContext | null>(null);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [mounted, setMounted] = useState<boolean>(false);

  // Hook Central de Agregação de Dados Financeiros (Trades, MT5 Account e Net PnL Real)
  const {
    trades,
    mt5Account,
    tradingMode,
    setSystemTradingMode,
    agentPerformance,
    isConnected: isTradingConnected,
    refetch: refetchTrading,
  } = useTradingData();

  useEffect(() => {
    setMounted(true);
  }, []);

  // Active choreographic mission state
  const [activeMission, setActiveMission] = useState<AgentMission>('NONE');

  // Modals state
  const [isSimulationOpen, setIsSimulationOpen] = useState<boolean>(false);
  const [isMT5ModalOpen, setIsMT5ModalOpen] = useState<boolean>(false);
  const [selectedAgent, setSelectedAgent] = useState<AgentStatus | null>(null);
  const [expandedScreen, setExpandedScreen] = useState<'PERFORMANCE' | 'MACRO' | 'TAPE' | null>(null);

  // Initial Data Fetch para agentes e contexto macro
  const fetchData = useCallback(async () => {
    try {
      // 1. Fetch Agents
      const { data: agentsData, error: agentsErr } = await supabase
        .from('agents_status')
        .select('*');
      if (!agentsErr && agentsData) {
        setAgents(agentsData);
      }

      // 2. Fetch Market Context
      const { data: marketData, error: marketErr } = await supabase
        .from('market_context')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(1);
      if (!marketErr && marketData && marketData.length > 0) {
        setMarketContext(marketData[0]);
      }
    } catch (err) {
      console.error('Erro ao carregar dados de agentes/macro do Supabase:', err);
    }
  }, []);

  useEffect(() => {
    fetchData();

    // Setup Supabase Realtime Channels para Agents, Trades, MT5 Account e Market Context
    const channel = supabase
      .channel('quant_office_realtime_main_dashboard')
      // 1. Ouvir eventos de UPDATE, INSERT, DELETE na tabela de agentes (agents_status)
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'agents_status' },
        (payload) => {
          if (payload.eventType === 'INSERT') {
            const newRow = payload.new as AgentStatus;
            setAgents((prev) => [...prev.filter((a) => a.agent_id !== newRow.agent_id), newRow]);
          } else if (payload.eventType === 'UPDATE') {
            const updatedRow = payload.new as AgentStatus;
            setAgents((prev) =>
              prev.map((a) => (a.agent_id === updatedRow.agent_id ? { ...a, ...updatedRow } : a))
            );
          } else if (payload.eventType === 'DELETE') {
            const oldRow = payload.old as AgentStatus;
            setAgents((prev) => prev.filter((a) => a.agent_id !== oldRow.agent_id));
          }
        }
      )
      // 2. Ouvir eventos de INSERT e UPDATE na tabela de histórico de ordens (trades_history)
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'trades_history' },
        () => {
          // Reação instantânea: atualiza trades e histórico de ordens fechadas pela VPS
          refetchTrading();
          fetchData();
        }
      )
      // 3. Ouvir eventos de UPDATE em mt5_account_status (atualização instantânea de saldo e PnL)
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'mt5_account_status' },
        () => {
          refetchTrading();
        }
      )
      // 4. Market Context Table Changes
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'market_context' },
        (payload) => {
          if (payload.new) {
            setMarketContext(payload.new as MarketContext);
            triggerDominoSequence();
          }
        }
      )
      .subscribe((status) => {
        if (status === 'SUBSCRIBED') {
          setIsConnected(true);
        } else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') {
          setIsConnected(false);
        }
      });

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchData, refetchTrading]);

  // Timers ref for coordinated Domino sequence
  const dominoTimersRef = useRef<NodeJS.Timeout[]>([]);

  const clearDominoTimers = () => {
    dominoTimersRef.current.forEach((t: NodeJS.Timeout) => clearTimeout(t));
    dominoTimersRef.current = [];
  };

  useEffect(() => {
    return () => {
      clearDominoTimers();
    };
  }, []);

  // =========================================================
  // COREOGRAFIA DE EFEITO DOMINÓ (S2 -> S3 -> S1)
  // =========================================================
  const triggerDominoSequence = useCallback(() => {
    clearDominoTimers();

    // Fase 1: News Macro (S2) levanta, fala frase aleatória e caminha rápido até o Auditor Quant (S3)
    setActiveMission('DOMINO_PHASE_1');

    // Fase 2 & 3: Após chegar e parar 1.5s na frente do S3 (~3.2s total),
    // News Macro começa a voltar para S2 e simultaneamente o Auditor Quant (S3) levanta e caminha para Sala 1
    const t1 = setTimeout(() => {
      setActiveMission('DOMINO_PHASE_3');
    }, 3200);

    // Fase 5: Auditor Quant chega em frente aos Operadores (Sala 1) contornando a Sala 6 por cima (~3.5s de caminhada).
    // Fica lá por 2 segundos exibindo o veredito visual ("Breakout Liberado!" ou "Risco Máximo")
    const t2 = setTimeout(() => {
      setActiveMission('DOMINO_PHASE_5');
    }, 6700);

    // Retorno do Auditor: Auditor volta rápido pelo corredor superior para sua cadeira no Setor 3
    const t3 = setTimeout(() => {
      setActiveMission('DOMINO_RETURN');
    }, 8900);

    // Finalização: todos sentados em seus postos
    const t4 = setTimeout(() => {
      setActiveMission('NONE');
    }, 12500);

    dominoTimersRef.current = [t1, t2, t3, t4];
  }, []);

  // Choreography triggers
  const handleTestNewsDelivery = () => {
    triggerDominoSequence();
  };

  const handleTestAuditDelivery = () => {
    setActiveMission('DELIVER_AUDIT');
    // Step 2 of audit chain: R&D engineer brings calibration to Trading desk
    setTimeout(() => {
      setActiveMission('INSTALL_CALIBRATION');
    }, 7000);
  };

  const handleTestCalibration = () => {
    setActiveMission('INSTALL_CALIBRATION');
  };

  const handleTestCRODirective = () => {
    setActiveMission('CRO_DIRECTIVE');
  };

  // Meeting & Walk actions
  const triggerMeeting = async () => {
    clearDominoTimers();
    // 1. Instant optimistic update: All 10 agents move to boardroom immediately
    setAgents((prev) =>
      prev.map((a) => ({
        ...a,
        current_state: 'IN_MEETING',
        last_thought: 'Convocado para o Conselho de Crise.',
      }))
    );

    try {
      await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'EMERGENCY_MEETING' }),
      });
      fetchData();
      refetchTrading();
    } catch (e) {
      console.error(e);
    }
  };

  const triggerReset = async () => {
    clearDominoTimers();
    setActiveMission('NONE');
    // Instant optimistic update: All 10 agents return to desks immediately
    setAgents((prev) =>
      prev.map((a) => ({
        ...a,
        current_state: 'IDLE',
        last_thought: 'No posto operacional...',
        allocation_weight: 1.0,
      }))
    );

    try {
      await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'RESET_IDLE' }),
      });
      fetchData();
      refetchTrading();
    } catch (e) {
      console.error(e);
    }
  };

  const isMeetingActive = agents.some((a) => (a.current_state || '').toUpperCase() === 'IN_MEETING');

  if (!mounted) {
    return (
      <div className="w-screen h-screen flex flex-col items-center justify-center bg-[#0f172a] text-cyan-400 font-mono">
        <div className="w-12 h-12 rounded-full border-2 border-cyan-400 border-t-transparent animate-spin mb-4 shadow-[0_0_20px_#00f0ff]" />
        <span className="text-sm font-bold tracking-widest uppercase">
          CARREGANDO CENTRO DE COMANDO 3D...
        </span>
      </div>
    );
  }

  return (
    <main className="relative w-screen h-screen overflow-hidden bg-[#0f172a]">
      {/* 100vw x 100vh 3D Isometric Cyberpunk Office Scene with Rooms */}
      <ErrorBoundary>
        <OfficeScene
          agents={agents}
          trades={trades}
          agentPerformance={agentPerformance}
          account={mt5Account}
          marketContext={marketContext}
          activeMission={activeMission}
          onMissionComplete={() => setActiveMission('NONE')}
          onSelectAgent={(agent) => setSelectedAgent(agent)}
          onExpandScreen={(screen) => setExpandedScreen(screen)}
          onOpenModal={() => setExpandedScreen('PERFORMANCE')}
          onOpenMT5Modal={() => setIsMT5ModalOpen(true)}
        />
      </ErrorBoundary>

      {/* Cyberpunk Game UI Command HUD Overlay */}
      <CommandHUD
        agents={agents}
        marketContext={marketContext}
        trades={trades}
        isConnected={isConnected || isTradingConnected}
        tradingMode={tradingMode}
        onToggleTradingMode={setSystemTradingMode}
        onOpenSimulation={() => setIsSimulationOpen(true)}
        onOpenMT5Modal={() => setIsMT5ModalOpen(true)}
        onSelectAgent={(agent) => setSelectedAgent(agent)}
        onTriggerMeeting={triggerMeeting}
        onTriggerReset={triggerReset}
        onTestNewsDelivery={handleTestNewsDelivery}
        onTestAuditDelivery={handleTestAuditDelivery}
        onTestCalibration={handleTestCalibration}
        onTestCRODirective={handleTestCRODirective}
        isMeetingActive={isMeetingActive}
      />

      {/* MT5 Account Balance Bar & TP/SL X-Ray Modal (Bar disabled, modal triggered from 3D Wall Panel or HUD) */}
      <MT5AccountPanel
        account={mt5Account}
        trades={trades}
        isOpen={isMT5ModalOpen}
        onClose={() => setIsMT5ModalOpen(false)}
        showFloatingBar={false}
      />

      {/* Detailed Modal for expanded screens or agent metrics */}
      <DetailModal
        selectedAgent={selectedAgent}
        expandedScreen={expandedScreen}
        trades={trades}
        agents={agents}
        marketContext={marketContext}
        onClose={() => {
          setSelectedAgent(null);
          setExpandedScreen(null);
        }}
      />

      {/* Simulation Events Modal */}
      <SimulationModal
        isOpen={isSimulationOpen}
        onClose={() => setIsSimulationOpen(false)}
        onActionTriggered={(action) => {
          if (action === 'DOMINO_NEWS') {
            triggerDominoSequence();
          } else if (action === 'EMERGENCY_MEETING') {
            setAgents((prev) =>
              prev.map((a) => ({
                ...a,
                current_state: 'IN_MEETING',
                last_thought: 'Convocado para o Conselho de Crise.',
              }))
            );
          } else if (action === 'RESET_IDLE') {
            setActiveMission('NONE');
            setAgents((prev) =>
              prev.map((a) => ({
                ...a,
                current_state: 'IDLE',
                last_thought: 'No posto operacional...',
                allocation_weight: 1.0,
              }))
            );
          } else if (action === 'QUARANTINE_BETA') {
            setAgents((prev) =>
              prev.map((a) =>
                a.agent_id === 'ops_beta'
                  ? { ...a, current_state: 'QUARANTINED', allocation_weight: 0 }
                  : a
              )
            );
          } else if (action === 'MARKET_ANALYSIS') {
            setAgents((prev) =>
              prev.map((a) =>
                a.agent_id.startsWith('ops_')
                  ? { ...a, current_state: 'ANALYZING', last_thought: 'Varrendo mercado...' }
                  : a
              )
            );
          } else if (action === 'ORDER_ALPHA') {
            setAgents((prev) =>
              prev.map((a) =>
                a.agent_id === 'ops_alpha'
                  ? { ...a, current_state: 'EXECUTING', last_thought: 'Executando ordem BUY BTCUSD!' }
                  : a
              )
            );
          }
        }}
      />
    </main>
  );
}
