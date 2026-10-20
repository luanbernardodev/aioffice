'use client';

import React, { useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Html } from '@react-three/drei';
import * as THREE from 'three';
import { AgentStatus, Trade, MarketContext, MT5AccountStatus, AgentPerformanceMap } from '@/types';
import { 
  Workstation, 
  CrisisBoardroomTable, 
  WallStreetBull,
  FrontRailing,
  BilliardsTable,
  WaterCooler,
  ServerRack,
  HoloGlobe,
  PingPongTable,
  LoungeSofa,
} from './Furniture';
import { VoxelAgent, AgentMission } from './VoxelAgent';
import { WallCanvasScreens } from './WallCanvasScreens';
import { getQuarantineSlot } from './officeLayout';

interface OfficeSceneProps {
  agents: AgentStatus[];
  trades: Trade[];
  agentPerformance?: AgentPerformanceMap;
  account?: MT5AccountStatus | null;
  marketContext: MarketContext | null;
  activeMission?: AgentMission;
  onMissionComplete?: () => void;
  onSelectAgent?: (agent: AgentStatus) => void;
  onExpandScreen?: (screen: 'PERFORMANCE' | 'MACRO' | 'TAPE') => void;
  onOpenModal?: () => void;
  onOpenMT5Modal?: () => void;
}

// -------------------------------------------------------------
// Sector Floor Demarcation Zone (Open Space with Crisp Neon Rim)
// -------------------------------------------------------------
const SectorFloorZone: React.FC<{
  position: [number, number, number];
  size: [number, number];
  color: string;
  borderColor: string;
  label: string;
}> = ({ position, size, color, borderColor, label }) => {
  const [w, d] = size;
  return (
    <group position={position}>
      {/* Floor Pad Slab (100% Opaque, depthWrite true) */}
      <mesh position={[0, 0.005, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[w, d]} />
        <meshStandardMaterial color={color} roughness={0.7} metalness={0.2} />
      </mesh>
      {/* Perimeter Solid Neon Borders */}
      <mesh position={[0, 0.015, -d / 2]}>
        <boxGeometry args={[w, 0.03, 0.08]} />
        <meshStandardMaterial color={borderColor} emissive={borderColor} emissiveIntensity={1.8} />
      </mesh>
      <mesh position={[0, 0.015, d / 2]}>
        <boxGeometry args={[w, 0.03, 0.08]} />
        <meshStandardMaterial color={borderColor} emissive={borderColor} emissiveIntensity={1.8} />
      </mesh>
      <mesh position={[-w / 2, 0.015, 0]}>
        <boxGeometry args={[0.08, 0.03, d]} />
        <meshStandardMaterial color={borderColor} emissive={borderColor} emissiveIntensity={1.8} />
      </mesh>
      <mesh position={[w / 2, 0.015, 0]}>
        <boxGeometry args={[0.08, 0.03, d]} />
        <meshStandardMaterial color={borderColor} emissive={borderColor} emissiveIntensity={1.8} />
      </mesh>
      {/* Floating Discreet Sector Label (No transform, no occlude, locked low z-index) */}
      <Html position={[0, 3.2, -d / 2 + 0.6]} center distanceFactor={22} zIndexRange={[5, 0]}>
        <div className="px-2.5 py-0.5 rounded-full bg-slate-950/85 border border-slate-700/80 text-[10px] font-mono font-bold tracking-wider uppercase text-slate-200 whitespace-nowrap shadow-lg pointer-events-none select-none">
          <span className="w-1.5 h-1.5 rounded-full inline-block mr-1.5" style={{ backgroundColor: borderColor }} />
          {label}
        </div>
      </Html>
    </group>
  );
};

export const OfficeScene: React.FC<OfficeSceneProps> = ({
  agents,
  trades,
  agentPerformance,
  account = null,
  marketContext,
  activeMission = 'NONE',
  onMissionComplete,
  onSelectAgent,
  onExpandScreen,
  onOpenModal,
  onOpenMT5Modal,
}) => {
  const getAgent = (id: string, name: string, sector: number): AgentStatus => {
    const exact = agents.find((a) => a.agent_id === id);
    const alias = agents.find(
      (a) =>
        (id === 'news_macro' && a.agent_id === 'news_desk') ||
        (id === 'auditor_quant' && a.agent_id === 'analytics') ||
        (id === 'rnd_engineer' && a.agent_id === 'rnd') ||
        (id === 'cro_manager' && a.agent_id === 'manager') ||
        (id === 'boardroom_chair' && a.agent_id === 'boardroom')
    );

    const source = exact || alias;
    if (source) {
      // If either canonical or legacy row indicates IN_MEETING or QUARANTINED, reflect it!
      const isAnyMeeting =
        (exact?.current_state || '').toUpperCase() === 'IN_MEETING' ||
        (alias?.current_state || '').toUpperCase() === 'IN_MEETING';
      const isAnyQuarantine =
        (exact?.current_state || '').toUpperCase() === 'QUARANTINED' ||
        (alias?.current_state || '').toUpperCase() === 'QUARANTINED';

      const finalState = isAnyMeeting
        ? 'IN_MEETING'
        : isAnyQuarantine
        ? 'QUARANTINED'
        : source.current_state || 'IDLE';

      return {
        ...source,
        agent_id: id,
        current_state: finalState,
      };
    }

    return {
      agent_id: id,
      name,
      sector,
      current_state: 'IDLE',
      last_thought: 'No posto operacional...',
      allocation_weight: 1.0,
    };
  };

  // Estrutura de Baias Operacionais da Sala 1 (Trading Floor)
  const OPS_DESKS = useMemo(() => [
    {
      key: 'alpha',
      name: 'Ops Alpha (Trend)',
      deskPos: [-9.40, 0, -8.0] as [number, number, number],
      deskRot: -Math.PI / 2,
      meetingPos: [-1.65, 0, 2.15] as [number, number, number],
      doorWaypoints: [[-6.0, -8.0]] as [number, number][],
      roleColor: '#00f0ff',
      visorColor: '#00f0ff',
      accentColor: '#00f0ff',
    },
    {
      key: 'delta',
      name: 'Ops Delta (SMC Scalper)',
      deskPos: [-9.40, 0, -3.5] as [number, number, number],
      deskRot: -Math.PI / 2,
      meetingPos: [-0.55, 0, 2.15] as [number, number, number],
      doorWaypoints: [[-6.0, -3.5]] as [number, number][],
      roleColor: '#06b6d4',
      visorColor: '#22d3ee',
      accentColor: '#06b6d4',
    },
    {
      key: 'beta',
      name: 'Ops Beta (Sniper)',
      deskPos: [-9.40, 0, 1.0] as [number, number, number],
      deskRot: -Math.PI / 2,
      meetingPos: [-1.65, 0, 4.85] as [number, number, number],
      doorWaypoints: [[-6.0, 1.0]] as [number, number][],
      roleColor: '#a855f7',
      visorColor: '#ef4444',
      accentColor: '#a855f7',
    },
    {
      key: 'epsilon',
      name: 'Ops Epsilon (VWAP Scalper)',
      deskPos: [-9.40, 0, 5.5] as [number, number, number],
      deskRot: -Math.PI / 2,
      meetingPos: [1.65, 0, 2.15] as [number, number, number],
      doorWaypoints: [[-6.0, 5.5]] as [number, number][],
      roleColor: '#6366f1',
      visorColor: '#818cf8',
      accentColor: '#6366f1',
    },
    {
      key: 'gamma',
      name: 'Ops Gamma (Breakout)',
      deskPos: [-9.40, 0, 10.0] as [number, number, number],
      deskRot: -Math.PI / 2,
      meetingPos: [0.55, 0, 2.15] as [number, number, number],
      doorWaypoints: [[-6.0, 10.0]] as [number, number][],
      roleColor: '#f97316',
      visorColor: '#f97316',
      accentColor: '#f97316',
    },
  ], []);

  // 1. Filtra estritamente os operadores ativos do Setor 1 que NÃO estão demitidos (current_state !== 'FIRED')
  const activeOpsList = useMemo(() => {
    const list = agents.filter(
      (a) =>
        (a.sector === 1 || a.agent_id.startsWith('ops_')) &&
        (a.current_state || '').toUpperCase() !== 'FIRED'
    );
    if (list.length > 0) return list;

    // Fallback inicial se os agentes do Supabase ainda estiverem carregando
    return [
      getAgent('ops_alpha', 'Ops Alpha (Trend)', 1),
      getAgent('ops_delta', 'Ops Delta (SMC Scalper)', 1),
      getAgent('ops_beta', 'Ops Beta (Sniper)', 1),
      getAgent('ops_epsilon', 'Ops Epsilon (VWAP Scalper)', 1),
      getAgent('ops_gamma', 'Ops Gamma (Breakout)', 1),
    ];
  }, [agents]);

  // Setores de Apoio (2 a 6)
  const newsMacro = getAgent('news_macro', 'News Desk (Macro)', 2);
  const auditorQuant = getAgent('auditor_quant', 'Auditor Quant', 3);
  const rndEngineer = getAgent('rnd_engineer', 'Engenheiro P&D', 4);
  const croManager = getAgent('cro_manager', 'Diretor CRO', 5);
  const boardroomChair = getAgent('boardroom_chair', 'Conselho Executivo', 6);

  const supportAgents = useMemo(
    () => [newsMacro, auditorQuant, rndEngineer, croManager, boardroomChair],
    [newsMacro, auditorQuant, rndEngineer, croManager, boardroomChair]
  );

  const allAgents = useMemo(() => [...activeOpsList, ...supportAgents], [activeOpsList, supportAgents]);
  const isMeetingActive = allAgents.some((a) => (a.current_state || '').toUpperCase() === 'IN_MEETING');

  // Mapeia dinamicamente operadores ativos para as baias da Sala 1 sem IDs hardcoded
  const opsConfigs = useMemo(() => {
    const assignedDeskKeys = new Set<string>();

    return activeOpsList.map((agent, index) => {
      // Extrai linhagem (ex: 'ops_gamma_v2' -> 'gamma', 'ops_beta' -> 'beta')
      const baseKey = agent.agent_id
        .replace(/_v\d+$/i, '')
        .replace(/^ops_/, '')
        .toLowerCase();

      // Encontra a baia de linhagem ou a próxima disponível
      let desk = OPS_DESKS.find((d) => d.key === baseKey && !assignedDeskKeys.has(d.key));
      if (!desk) {
        desk = OPS_DESKS.find((d) => !assignedDeskKeys.has(d.key)) || OPS_DESKS[index % OPS_DESKS.length];
      }
      assignedDeskKeys.add(desk.key);

      const qSlot = getQuarantineSlot(agent.agent_id);

      return {
        agent,
        deskPos: desk.deskPos,
        deskRot: desk.deskRot,
        meetingPos: desk.meetingPos,
        quarantinePos: qSlot.pos,
        quarantineFacingRot: qSlot.facingRot,
        doorWaypoints: desk.doorWaypoints,
        roleColor: desk.roleColor,
        visorColor: desk.visorColor,
      };
    });
  }, [activeOpsList, OPS_DESKS]);

  // Mapeamento das Workstations físicas para vincular o operador atualmente na baia
  const opsDeskOccupants = useMemo(() => {
    return OPS_DESKS.map((desk) => {
      const occupant = opsConfigs.find((c) => {
        const baseKey = c.agent.agent_id
          .replace(/_v\d+$/i, '')
          .replace(/^ops_/, '')
          .toLowerCase();
        return baseKey === desk.key;
      })?.agent;

      return {
        desk,
        occupant,
      };
    });
  }, [OPS_DESKS, opsConfigs]);

  // Configuração consolidada de todos os agentes renderizados em 3D
  const agentConfigs = useMemo(
    () => [
      ...opsConfigs,
      {
        agent: newsMacro,
        deskPos: [9.40, 0, -5.0] as [number, number, number],
        deskRot: Math.PI / 2,
        meetingPos: [-0.55, 0, 4.85] as [number, number, number],
        quarantinePos: getQuarantineSlot('news_macro').pos,
        quarantineFacingRot: getQuarantineSlot('news_macro').facingRot,
        doorWaypoints: [[6.0, -5.0]] as [number, number][],
        roleColor: '#f59e0b',
        visorColor: '#f59e0b',
      },
      {
        agent: auditorQuant,
        deskPos: [9.40, 0, 2.0] as [number, number, number],
        deskRot: Math.PI / 2,
        meetingPos: [0.55, 0, 4.85] as [number, number, number],
        quarantinePos: getQuarantineSlot('auditor_quant').pos,
        quarantineFacingRot: getQuarantineSlot('auditor_quant').facingRot,
        doorWaypoints: [[6.0, 2.0]] as [number, number][],
        roleColor: '#10b981',
        visorColor: '#10b981',
      },
      {
        agent: rndEngineer,
        deskPos: [9.40, 0, 7.8] as [number, number, number],
        deskRot: Math.PI / 2,
        meetingPos: [1.65, 0, 4.85] as [number, number, number],
        quarantinePos: getQuarantineSlot('rnd_engineer').pos,
        quarantineFacingRot: getQuarantineSlot('rnd_engineer').facingRot,
        doorWaypoints: [[6.0, 7.8]] as [number, number][],
        roleColor: '#059669',
        visorColor: '#d946ef',
      },
      {
        agent: croManager,
        deskPos: [0.0, 0, -5.90] as [number, number, number],
        deskRot: Math.PI,
        meetingPos: [2.60, 0, 3.50] as [number, number, number],
        quarantinePos: getQuarantineSlot('cro_manager').pos,
        quarantineFacingRot: getQuarantineSlot('cro_manager').facingRot,
        doorWaypoints: [[0.0, -3.0]] as [number, number][],
        roleColor: '#eab308',
        visorColor: '#eab308',
      },
      {
        agent: boardroomChair,
        deskPos: [-2.60, 0, 3.50] as [number, number, number],
        deskRot: Math.PI / 2,
        meetingPos: [-2.60, 0, 3.50] as [number, number, number],
        quarantinePos: getQuarantineSlot('boardroom_chair').pos,
        quarantineFacingRot: getQuarantineSlot('boardroom_chair').facingRot,
        doorWaypoints: [[-1.2, 3.5]] as [number, number][],
        roleColor: '#c084fc',
        visorColor: '#c084fc',
      },
    ],
    [opsConfigs, newsMacro, auditorQuant, rndEngineer, croManager, boardroomChair]
  );

  const handleScreenClick = () => {
    if (onOpenModal) {
      onOpenModal();
    } else if (onExpandScreen) {
      onExpandScreen('PERFORMANCE');
    }
  };

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-[#090d16]">
      <Canvas
        camera={{ position: [22, 24, 22], fov: 28 }}
        className="w-full h-full"
      >
        {/* Crisp Slate-Navy Studio Backdrop */}
        <color attach="background" args={['#0f172a']} />

        <OrbitControls
          enableDamping
          dampingFactor={0.06}
          minPolarAngle={Math.PI / 6}
          maxPolarAngle={Math.PI / 2.3}
          minDistance={10}
          maxDistance={65}
          target={[0, 1.2, 1.0]}
        />

        {/* ========================================================= */}
        {/* 1. BRIGHT LAB HIGH-TECH LIGHTING                          */}
        {/* ========================================================= */}
        <ambientLight intensity={2.8} color="#ffffff" />
        <hemisphereLight args={['#e0f2fe', '#1e293b', 2.0]} />
        <directionalLight position={[20, 35, 20]} intensity={2.5} color="#ffffff" castShadow />

        {/* Soft Point Lights over Islands */}
        <pointLight position={[-10, 4.5, -5]} color="#00f0ff" intensity={1.8} distance={12} />
        <pointLight position={[-10, 4.5, 2]} color="#a855f7" intensity={1.8} distance={12} />
        <pointLight position={[-10, 4.5, 9]} color="#f97316" intensity={1.8} distance={12} />
        <pointLight position={[10, 4.5, -5]} color="#f59e0b" intensity={1.8} distance={12} />
        <pointLight position={[10, 4.5, 2]} color="#10b981" intensity={1.8} distance={12} />
        <pointLight position={[0, 4.5, -6.5]} color="#eab308" intensity={1.8} distance={12} />
        <pointLight position={[0, 4.5, 2.5]} color="#c084fc" intensity={1.8} distance={12} />

        {/* ========================================================= */}
        {/* 2. PISO PRINCIPAL: CINZA AZULADO CLARO FOSCO (#475569)     */}
        {/* Solid slab, 100% opaque, depthWrite true, no dark grid     */}
        {/* ========================================================= */}
        <mesh position={[0, -0.25, 1.0]} receiveShadow>
          <boxGeometry args={[44.0, 0.5, 36.0]} />
          <meshStandardMaterial
            color="#475569"
            roughness={0.8}
            metalness={0.2}
          />
        </mesh>

        {/* Central Walkway Inlay (Solid Dark Slate Accent Line) */}
        <mesh position={[0, 0.002, 1.0]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[3.6, 26.0]} />
          <meshStandardMaterial
            color="#334155"
            roughness={0.7}
            metalness={0.3}
          />
        </mesh>

        {/* ========================================================= */}
        {/* SECTOR FLOOR DEMARCATIONS (OPEN SPACE WITH NEON RIM)      */}
        {/* ========================================================= */}
        {/* Setor 1: Trading Desk (5 Traders & Scalpers) */}
        <SectorFloorZone
          position={[-10.0, 0, 1.0]}
          size={[6.8, 22.0]}
          color="#1e293b"
          borderColor="#00f0ff"
          label="SETOR 1: TRADING DESK (5 SCALPERS & PROS)"
        />

        {/* Setor 2: Notícias Macro */}
        <SectorFloorZone
          position={[10.0, 0, -5.0]}
          size={[6.0, 6.2]}
          color="#1e293b"
          borderColor="#f59e0b"
          label="SETOR 2: RADAR MACRO"
        />

        {/* Setor 3 & 4: Lab Quant & P&D (Adjusted Z-depth so it does not overlap Lounge) */}
        <SectorFloorZone
          position={[10.0, 0, 4.8]}
          size={[6.2, 10.2]}
          color="#1e293b"
          borderColor="#10b981"
          label="SETOR 3 & 4: LAB QUANT & P&D"
        />

        {/* Setor 5: Diretoria CRO */}
        <SectorFloorZone
          position={[0.0, 0, -6.5]}
          size={[6.2, 5.5]}
          color="#1e293b"
          borderColor="#eab308"
          label="SETOR 5: DIRETORIA CRO"
        />

        {/* Setor 6: Conselho de Crise (Roomy frame for all 10 Boardroom chairs) */}
        <SectorFloorZone
          position={[0.0, 0, 3.5]}
          size={[7.2, 4.4]}
          color="#1e293b"
          borderColor="#c084fc"
          label="SETOR 6: CONSELHO DE CRISE"
        />

        {/* Área Lounge & Descompressão (Quarentena - Adjusted to leave clean corridor to Sector 3) */}
        <SectorFloorZone
          position={[14.2, 0, 14.4]}
          size={[10.2, 5.8]}
          color="#1e293b"
          borderColor="#38bdf8"
          label="LOUNGE & DESCOMPRESSÃO"
        />

        {/* ========================================================= */}
        {/* 3. PAREDE DE FUNDO SÓLIDA COM FRISOS NEON (Z = -12)       */}
        {/* ========================================================= */}
        <group position={[0, 4.5, -12.0]}>
          {/* Main Solid Wall Slab */}
          <mesh position={[0, 0, 0]}>
            <boxGeometry args={[44.0, 9.0, 0.4]} />
            <meshStandardMaterial color="#0f172a" roughness={0.4} metalness={0.8} />
          </mesh>

          {/* Top Neon Gold Trim */}
          <mesh position={[0, 4.52, 0.05]}>
            <boxGeometry args={[44.1, 0.08, 0.42]} />
            <meshStandardMaterial color="#eab308" emissive="#eab308" emissiveIntensity={2.0} />
          </mesh>

          {/* Horizontal Decorative Neon Grooves */}
          <mesh position={[0, 2.8, 0.21]}>
            <boxGeometry args={[43.8, 0.04, 0.02]} />
            <meshStandardMaterial color="#eab308" emissive="#eab308" emissiveIntensity={1.8} />
          </mesh>
          <mesh position={[0, -2.8, 0.21]}>
            <boxGeometry args={[43.8, 0.04, 0.02]} />
            <meshStandardMaterial color="#00f0ff" emissive="#00f0ff" emissiveIntensity={1.5} />
          </mesh>

          {/* Bottom Baseboard Curb */}
          <mesh position={[0, -4.42, 0.05]}>
            <boxGeometry args={[44.1, 0.16, 0.42]} />
            <meshStandardMaterial color="#1e293b" metalness={0.6} />
          </mesh>
        </group>

        {/* ========================================================= */}
        {/* 4. TELÕES NATIVOS NA PAREDE (CANVAS TEXTURE — ZERO HTML)  */}
        {/* ========================================================= */}
        <WallCanvasScreens
          account={account}
          trades={trades}
          agents={allAgents}
          marketContext={marketContext}
          onOpenModal={handleScreenClick}
          onOpenMT5Modal={onOpenMT5Modal || handleScreenClick}
        />

        {/* ========================================================= */}
        {/* 5. GUARDA-CORPO FRONTAL + TOURO DE OURO (WALL STREET BULL) */}
        {/* ========================================================= */}
        <FrontRailing zPos={18.0} />
        <WallStreetBull position={[0, 0, 14.5]} />

        {/* ========================================================= */}
        {/* 6. ÁREA DE DESCANSO / LOUNGE (DIREITA FRONTAL)            */}
        {/* ========================================================= */}
        <PingPongTable position={[10.5, 0, 14.4]} rotation={[0, Math.PI / 2, 0]} />
        <BilliardsTable position={[15.2, 0, 14.4]} rotation={[0, Math.PI / 2, 0]} />
        <WaterCooler position={[18.4, 0, 12.8]} />
        {/* Sofás no Lounge para Ops Delta e Ops Epsilon */}
        <LoungeSofa position={[18.4, 0, 15.8]} rotation={[0, -Math.PI / 2, 0]} width={2.0} />
        <LoungeSofa position={[13.8, 0, 16.6]} rotation={[0, 0, 0]} width={1.8} />

        {/* ========================================================= */}
        {/* 7. ILHAS DE MESAS DE TRADING (OPEN SPACE WORKSTATIONS)    */}
        {/* Tabletop #64748b, Base #334155, Fita LED Sólida, 2 Monitores */}
        {/* ========================================================= */}
        {opsDeskOccupants.map(({ desk, occupant }) => {
          const isQuarantined = occupant
            ? (occupant.current_state || '').toUpperCase() === 'QUARANTINED' || occupant.allocation_weight === 0
            : false;
          const isExecuting = occupant ? (occupant.current_state || '').toUpperCase() === 'EXECUTING' : false;
          const stateColor = isQuarantined
            ? '#ef4444'
            : isExecuting
            ? '#10b981'
            : desk.roleColor;

          return (
            <Workstation
              key={desk.key}
              position={[desk.deskPos[0] - 0.6, 0, desk.deskPos[2]]}
              rotation={[0, Math.PI / 2, 0]}
              accentColor={desk.accentColor}
              stateColor={stateColor}
              isExecuting={isExecuting}
              isQuarantined={isQuarantined}
              agentLabel={occupant ? occupant.name : desk.name}
            />
          );
        })}

        {/* Ilha 4: Setor 2 (News Desk Oráculo - Amarelo Ouro) */}
        <Workstation
          position={[10.0, 0, -5.0]}
          rotation={[0, -Math.PI / 2, 0]}
          accentColor="#f59e0b"
          stateColor="#f59e0b"
          agentLabel="News Desk"
        />
        {/* Holographic News Antenna/Globe on News Desk */}
        <HoloGlobe position={[9.2, 0.78, -5.0]} />

        {/* Ilha 5: Setor 3 (Auditor Quant) & Setor 4 (Engenheiro P&D) - Verde Esmeralda */}
        <Workstation
          position={[10.0, 0, 2.0]}
          rotation={[0, -Math.PI / 2, 0]}
          accentColor="#10b981"
          stateColor="#10b981"
          agentLabel="Auditor Quant"
        />
        <Workstation
          position={[10.0, 0, 7.8]}
          rotation={[0, -Math.PI / 2, 0]}
          accentColor="#10b981"
          stateColor="#d946ef"
          agentLabel="Engenheiro P&D"
        />
        {/* High-Tech Blinking Server Racks next to Quant Lab & P&D */}
        <ServerRack position={[12.4, 0, 0.5]} rotation={[0, -Math.PI / 2, 0]} />
        <ServerRack position={[12.4, 0, 9.2]} rotation={[0, -Math.PI / 2, 0]} />

        {/* Ilha 6: Setor 5 (Diretor CRO - Dourado Executivo) */}
        <Workstation
          position={[0.0, 0, -6.5]}
          rotation={[0, 0, 0]}
          accentColor="#eab308"
          stateColor="#eab308"
          agentLabel="Diretor CRO"
        />

        {/* Ilha 6: Setor 6 (Mesa Executiva Retangular da Reunião de Crise) */}
        <CrisisBoardroomTable
          position={[0.0, 0, 3.5]}
          isMeetingActive={isMeetingActive}
        />

        {/* ========================================================= */}
        {/* 8. BONECOS 3D COM PÍLULAS MINIMALISTAS DE 1 LINHA         */}
        {/* ========================================================= */}
        {agentConfigs.map((cfg) => {
          const isActor =
            cfg.agent.agent_id.includes('news') ||
            cfg.agent.agent_id.includes('auditor') ||
            cfg.agent.agent_id.includes('analytics');
          const isDominoNews = activeMission.startsWith('DOMINO') || activeMission === 'DELIVER_NEWS';
          // Trava de Estado (State Isolation): Só entrega a missão dominó para o mensageiro e auditor
          const isolatedMission = isDominoNews && !isActor ? 'NONE' : activeMission;

          return (
            <VoxelAgent
              key={cfg.agent.agent_id}
              agent={cfg.agent}
              trades={trades}
              agentPerformance={agentPerformance}
              marketContext={marketContext}
              deskPos={cfg.deskPos}
              deskRotation={cfg.deskRot}
              meetingPos={cfg.meetingPos}
              quarantinePos={cfg.quarantinePos}
              quarantineFacingRot={cfg.quarantineFacingRot}
              doorWaypoints={cfg.doorWaypoints}
              roleColor={cfg.roleColor}
              visorColor={cfg.visorColor}
              activeMission={isolatedMission}
              onMissionComplete={onMissionComplete}
              onSelectAgent={onSelectAgent}
            />
          );
        })}
      </Canvas>
    </div>
  );
};

export default OfficeScene;
