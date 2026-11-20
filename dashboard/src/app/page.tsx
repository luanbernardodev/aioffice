'use client';

import React, { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { AgentStatus } from '@/types';
import { useOffice } from '@/hooks/useOffice';
import { OfficeHud } from '@/components/office/OfficeHud';
import { ErrorBoundary } from '@/components/ErrorBoundary';

// Cena 3D só no navegador (WebGL)
const TradingFloor = dynamic(() => import('@/components/office/TradingFloor'), {
  ssr: false,
  loading: () => (
    <div className="absolute inset-0 grid place-items-center bg-[#070a12] text-slate-400 text-sm tracking-widest">
      MONTANDO O ESCRITÓRIO…
    </div>
  ),
});

export default function DashboardPage() {
  const office = useOffice();
  const [selected, setSelected] = useState<AgentStatus | null>(null);
  const [, setTick] = useState(0);

  // re-render leve para expirar plaquinhas/avisos de eventos antigos
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 2000);
    return () => clearInterval(id);
  }, []);

  // modo demonstração: /?teste-evento dispara um fechamento fictício a cada 8 s (só visual, sem banco)
  const { agents, simulateClose } = office;
  useEffect(() => {
    if (typeof window === 'undefined' || !new URLSearchParams(window.location.search).has('teste-evento')) return;
    let i = 0;
    const fire = () => {
      if (!agents.length) return;
      const a = agents[i++ % agents.length];
      simulateClose(a.agent_id, i % 2 ? +(Math.random() * 9 + 1).toFixed(2) : -(Math.random() * 9 + 1).toFixed(2));
    };
    const first = setTimeout(fire, 1500);
    const id = setInterval(fire, 8000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [agents, simulateClose]);

  // mantém a ficha do agente selecionado atualizada com o Realtime
  const current = selected ? office.agents.find((a) => a.agent_id === selected.agent_id) || selected : null;

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-[#070a12]">
      <ErrorBoundary>
        <TradingFloor
          agents={office.agents}
          stats={office.stats}
          competition={office.competition}
          events={office.events}
          selectedId={current?.agent_id ?? null}
          onSelect={setSelected}
        />
      </ErrorBoundary>
      <OfficeHud
        agents={office.agents}
        trades={office.trades}
        account={office.account}
        competition={office.competition}
        auditor={office.auditor}
        events={office.events}
        recentCloses={office.recentCloses}
        connected={office.connected}
        selected={current}
        onSelect={setSelected}
      />
    </main>
  );
}
