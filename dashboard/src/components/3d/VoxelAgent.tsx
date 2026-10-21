'use client';

import React, { useRef, useState, useEffect, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { AgentStatus, AgentState, Trade, MarketContext, AgentPerformanceMap } from '@/types';
import { Zap, Cpu, Activity, Lock, Users } from 'lucide-react';
import { getAgentNetPnL, formatPnL } from '@/lib/pnlUtils';
import {
  buildOrthogonalPathToMeeting,
  buildOrthogonalPathToQuarantine,
  buildOrthogonalPathToDesk,
} from './officeLayout';

export type AgentMission = 
  | 'NONE'
  | 'DELIVER_NEWS'
  | 'DELIVER_AUDIT'
  | 'INSTALL_CALIBRATION'
  | 'CRO_DIRECTIVE'
  | 'DOMINO_PHASE_1'
  | 'DOMINO_PHASE_2'
  | 'DOMINO_PHASE_3'
  | 'DOMINO_PHASE_5'
  | 'DOMINO_RETURN';

interface VoxelAgentProps {
  agent: AgentStatus;
  trades?: Trade[];
  agentPerformance?: AgentPerformanceMap;
  marketContext?: MarketContext | null;
  deskPos: [number, number, number];
  deskRotation?: number; // Y rotation angle
  meetingPos: [number, number, number];
  quarantinePos: [number, number, number];
  quarantineFacingRot?: number;
  doorWaypoints?: [number, number][]; // waypoints from desk to central corridor
  roleColor: string;
  visorColor: string;
  activeMission?: AgentMission;
  onMissionComplete?: () => void;
  onSelectAgent?: (agent: AgentStatus) => void;
}

const NEWS_MESSENGER_PHRASES = [
  '📰 Notícia saindo do forno!',
  '⚡ Bomba no radar!',
  '🚨 Urgente na Bloomberg!',
  '🔥 Catalisador macro no terminal!',
  '📊 Furo de liquidez detectado!',
];

const AUDITOR_QUANT_PHRASES = [
  '🧐 Essa bomba eu quero ver...',
  '⚙️ Ajustando o risco das mesas!',
  '🧹 Limpando os filtros!',
  '📈 Volatilidade é oportunidade!',
  '🎯 Estrategista quantitativo em ação!',
];

export const VoxelAgent: React.FC<VoxelAgentProps> = ({
  agent,
  trades = [],
  agentPerformance,
  marketContext = null,
  deskPos,
  deskRotation = 0,
  meetingPos,
  quarantinePos,
  quarantineFacingRot = 0,
  doorWaypoints = [],
  roleColor,
  visorColor,
  activeMission = 'NONE',
  onMissionComplete,
  onSelectAgent,
}) => {
  const groupRef = useRef<THREE.Group>(null);
  const leftLegRef = useRef<THREE.Group>(null);
  const rightLegRef = useRef<THREE.Group>(null);
  const leftArmRef = useRef<THREE.Group>(null);
  const rightArmRef = useRef<THREE.Group>(null);
  const visorRef = useRef<THREE.Mesh>(null);

  // Position state (starts at desk)
  const currentPos = useRef<THREE.Vector3>(new THREE.Vector3(deskPos[0], deskPos[1], deskPos[2]));
  const currentRot = useRef<number>(deskRotation);

  // Accelerated brisk trading-floor walking cadence & physics (doubled speed)
  const walkSeed = useMemo(() => {
    let hash = 0;
    const id = agent.agent_id || 'agent';
    for (let i = 0; i < id.length; i++) {
      hash = (hash << 5) - hash + id.charCodeAt(i);
      hash |= 0;
    }
    const seed = (Math.abs(hash) % 1000) / 1000;
    return {
      stepFreq: 18.0 + seed * 6.0,        // Doubled step cadence (18.0 to 24.0 rad/s)
      stepPhase: seed * Math.PI * 2,     // Random phase offset (0 to 2*PI)
      moveSpeed: 0.085 + seed * 0.035,   // Doubled movement speed factor (0.085 to 0.120)
      bobAmount: 0.05 + seed * 0.025,    // Snappy trading floor bobbing height
      swingAmp: 0.55 + seed * 0.20,      // Accelerated arm & leg swing amplitude
    };
  }, [agent.agent_id]);

  // Waypoints navigation system
  const [activeWaypoints, setActiveWaypoints] = useState<[number, number][]>([]);
  const [waypointIndex, setWaypointIndex] = useState<number>(0);
  const [customThought, setCustomThought] = useState<string | null>(null);

  const state = (agent.current_state || 'IDLE').toUpperCase() as AgentState;
  const isQuarantined = state === 'QUARANTINED' || agent.allocation_weight === 0;
  const isMeeting = state === 'IN_MEETING';

  const room1Briefing: [number, number] = [-6.2, -4.0];
  const isNewsAgent = agent.agent_id.includes('news');
  const isAuditorAgent = agent.agent_id.includes('auditor') || agent.agent_id.includes('analytics');
  const isImmunized = (agent.last_thought || '').includes('Imunizada') || (agent.last_thought || '').includes('Imunizado');

  // Monitora pensamentos de vacina pós-morte e imunização em tempo real via Supabase
  useEffect(() => {
    const thought = agent.last_thought || '';
    if (thought.includes('Vacina gerada')) {
      setCustomThought(thought);
      const timer = setTimeout(() => setCustomThought(null), 9000);
      return () => clearTimeout(timer);
    }
    if (thought.includes('Imunizada') || thought.includes('Imunizado')) {
      setCustomThought('🛡️ Estratégia Imunizada!');
      const timer = setTimeout(() => setCustomThought(null), 7000);
      return () => clearTimeout(timer);
    }
  }, [agent.last_thought]);

  // =========================================================
  // STRICT STATE MACHINE: "CADA UM NO SEU QUADRADO" + DOMINO + CORREDOR CENTRAL [0, 0]
  // =========================================================
  useEffect(() => {
    const curPos: [number, number, number] = [currentPos.current.x, 0, currentPos.current.z];

    // 1. EMERGENCY MEETING (Setor 6)
    if (isMeeting) {
      const approachWaypoints = buildOrthogonalPathToMeeting(curPos, meetingPos, doorWaypoints);
      setActiveWaypoints(approachWaypoints);
      setWaypointIndex(0);
      setCustomThought('Reunião convocada: deliberando no Conselho de Crise.');
      return;
    }

    // 2. QUARANTINED (ou 0x weight) -> Slot exclusivo anti-overlap no Lounge via Corredor Central
    if (isQuarantined) {
      const path = buildOrthogonalPathToQuarantine(curPos, quarantinePos, doorWaypoints);
      setActiveWaypoints(path);
      setWaypointIndex(0);
      setCustomThought('Suspenso pelo CRO. Na área de descanso.');
      return;
    }

    // =========================================================
    // COREOGRAFIA DE EFEITO DOMINÓ (S2 -> S3 -> S1)
    // =========================================================
    const isDominoNews = activeMission.startsWith('DOMINO') || activeMission === 'DELIVER_NEWS';

    // HARD-LOCK DE GUARDA: Operadores e demais setores NUNCA andam durante evento de notícia/dominó
    if (isDominoNews && !isNewsAgent && !isAuditorAgent) {
      setActiveWaypoints([]);
      setCustomThought(null);
      return;
    }
    
    // FASE 1: O Mensageiro (News Macro levanta e caminha rápido até o Auditor S3)
    if (activeMission === 'DOMINO_PHASE_1' || activeMission === 'DELIVER_NEWS') {
      if (isNewsAgent) {
        const randPhrase = NEWS_MESSENGER_PHRASES[Math.floor(Math.random() * NEWS_MESSENGER_PHRASES.length)];
        setCustomThought(randPhrase);
        const pathNewsToAuditor: [number, number][] = [
          [6.5, -5.0],
          [6.5, 2.0],
          [7.8, 2.0],
        ];
        setActiveWaypoints(pathNewsToAuditor);
        setWaypointIndex(0);
      }
      return;
    }

    // FASE 2 & FASE 3: News volta para S2; Auditor Quant levanta e caminha para Sala 1
    // ROTAS EM "L" ORTOGONAIS: Passa obrigatoriamente pelo Corredor Central [0, 0]
    if (activeMission === 'DOMINO_PHASE_2' || activeMission === 'DOMINO_PHASE_3') {
      if (isNewsAgent) {
        setCustomThought('Notícia entregue ao auditor. Retornando ao terminal.');
        const pathNewsBack: [number, number][] = [
          [6.5, 2.0],
          [6.5, -5.0],
          [deskPos[0], deskPos[2]],
        ];
        setActiveWaypoints(pathNewsBack);
        setWaypointIndex(0);
      }

      if (isAuditorAgent) {
        const randPhrase = AUDITOR_QUANT_PHRASES[Math.floor(Math.random() * AUDITOR_QUANT_PHRASES.length)];
        setCustomThought(randPhrase);
        // Rota Ortogonal via Corredor Central [0, 0] (Desvia completamente da Sala 6):
        const pathAuditorToOps: [number, number][] = [
          [6.0, 2.0],   // Saída do Setor 3
          [6.0, 0.0],   // Alinha no Corredor Leste-Oeste Z = 0
          [0.0, 0.0],   // Hub: Corredor Central (x: 0, z: 0)
          [-6.0, 0.0],  // Corredor do Setor 1
          [-6.0, -4.0], // Frente aos operadores
          room1Briefing, // Briefing [-6.2, -4.0]
        ];
        setActiveWaypoints(pathAuditorToOps);
        setWaypointIndex(0);
      }
      return;
    }

    // FASE 5: O Veredito (Auditor Quant chega aos operadores e exibe o veredito por 2 segundos)
    if (activeMission === 'DOMINO_PHASE_5') {
      if (isAuditorAgent) {
        const isRedFlag = marketContext?.red_flag_pause_trading === true;
        const verdict = isRedFlag
          ? '🛑 Risco Máximo, Segurem as ordens!'
          : (Math.random() > 0.4 ? '🚀 Breakout Liberado!' : '⚡ Volatilidade aprovada: Alpha e Gamma liberados!');
        setCustomThought(verdict);
        setActiveWaypoints([]); // Para estático em frente aos operadores
      }
      return;
    }

    // RETORNO DO AUDITOR: Volta rápido para sua cadeira no Setor 3 via Corredor Central [0, 0]
    if (activeMission === 'DOMINO_RETURN') {
      if (isAuditorAgent) {
        setCustomThought('Veredito entregue às mesas. Retornando ao Lab Quant.');
        const pathAuditorReturn: [number, number][] = [
          [-6.2, -4.0],
          [-6.0, -4.0],
          [-6.0, 0.0],
          [0.0, 0.0],   // Corredor Central
          [6.0, 0.0],
          [6.0, 2.0],
          [deskPos[0], deskPos[2]],
        ];
        setActiveWaypoints(pathAuditorReturn);
        setWaypointIndex(0);
      }
      return;
    }

    // 4. MISSION: AUDIT & ANALYSIS (Sector 3 -> Sector 4)
    if (activeMission === 'DELIVER_AUDIT' && isAuditorAgent) {
      const pathOut: [number, number][] = [
        [6.0, 2.0],
        [6.0, 7.8],
        [8.2, 7.8],
      ];
      setActiveWaypoints(pathOut);
      setWaypointIndex(0);
      setCustomThought('📊 Entregando diagnóstico estatístico ao P&D!');

      const t = setTimeout(() => {
        const pathBack: [number, number][] = [
          [8.2, 7.8],
          [6.0, 7.8],
          [6.0, 2.0],
          [deskPos[0], deskPos[2]],
        ];
        setActiveWaypoints(pathBack);
        setWaypointIndex(0);
        setCustomThought('Auditoria compartilhada. Retornando à bancada.');
        if (onMissionComplete) setTimeout(onMissionComplete, 3500);
      }, 4500);
      return () => clearTimeout(t);
    }

    // 5. MISSION: R&D CALIBRATION (Sector 4 -> Sector 1 via Corredor Central [0, 0])
    if (activeMission === 'INSTALL_CALIBRATION' && agent.agent_id.includes('rnd')) {
      const pathOut: [number, number][] = [
        [6.0, 7.8],
        [6.0, 0.0],
        [0.0, 0.0],   // Hub: Corredor Central
        [-6.0, 0.0],
        [-6.0, -4.0],
        room1Briefing,
      ];
      setActiveWaypoints(pathOut);
      setWaypointIndex(0);
      setCustomThought('🛠️ Instalando novos parâmetros de stop nos terminais!');

      const t = setTimeout(() => {
        const pathBack: [number, number][] = [
          room1Briefing,
          [-6.0, -4.0],
          [-6.0, 0.0],
          [0.0, 0.0], // Hub: Corredor Central
          [6.0, 0.0],
          [6.0, 7.8],
          [deskPos[0], deskPos[2]],
        ];
        setActiveWaypoints(pathBack);
        setWaypointIndex(0);
        setCustomThought('Parâmetros instalados. Retornando ao P&D.');
        if (onMissionComplete) setTimeout(onMissionComplete, 3500);
      }, 4500);
      return () => clearTimeout(t);
    }

    // 6. MISSION: CRO RISK DIRECTIVE (Sector 5 -> Sector 1 via Corredor Central [0, 0])
    if (activeMission === 'CRO_DIRECTIVE' && (agent.agent_id.includes('cro') || agent.agent_id.includes('manager'))) {
      const pathOut: [number, number][] = [
        [0.0, -3.0],
        [0.0, 0.0],   // Hub: Corredor Central
        [-6.0, 0.0],
        [-6.0, -4.0],
        room1Briefing,
      ];
      setActiveWaypoints(pathOut);
      setWaypointIndex(0);
      setCustomThought('🛡️ Diretoria CRO: Inspecionando conformidade e teto de risco!');

      const t = setTimeout(() => {
        const pathBack: [number, number][] = [
          room1Briefing,
          [-6.0, -4.0],
          [-6.0, 0.0],
          [0.0, 0.0],   // Hub: Corredor Central
          [0.0, -3.0],
          [deskPos[0], deskPos[2]],
        ];
        setActiveWaypoints(pathBack);
        setWaypointIndex(0);
        setCustomThought('Inspeção concluída. Diretoria operando em conformidade.');
        if (onMissionComplete) setTimeout(onMissionComplete, 3500);
      }, 4500);
      return () => clearTimeout(t);
    }

    // 7. DEFAULT (IDLE, ANALYZING, EXECUTING, NONE): RETORNO SEGURO PARA A MESA
    const distFromDesk = Math.hypot(currentPos.current.x - deskPos[0], currentPos.current.z - deskPos[2]);
    if (distFromDesk < 0.28) {
      setActiveWaypoints([]);
    } else {
      const returnPath = buildOrthogonalPathToDesk(curPos, deskPos, doorWaypoints);
      setActiveWaypoints(returnPath);
      setWaypointIndex(0);
    }
    setCustomThought(null);
  }, [state, isQuarantined, isMeeting, activeMission, quarantinePos, meetingPos, deskPos]);

  // =========================================================
  // ANIMATION FRAME LOOP: WAYPOINTS & ACCELERATED LIMB MOVEMENT
  // =========================================================
  useFrame(({ clock }) => {
    if (!groupRef.current) return;

    let targetX = deskPos[0];
    let targetZ = deskPos[2];
    let targetFaceRot = deskRotation;

    // HARD-LOCK DE GUARDA: Operadores e demais setores rigidamente travados durante evento dominó
    const isDominoNews = activeMission.startsWith('DOMINO') || activeMission === 'DELIVER_NEWS';
    const isHardLocked = isDominoNews && !isNewsAgent && !isAuditorAgent && !isMeeting && !isQuarantined;

    if (isHardLocked) {
      targetX = deskPos[0];
      targetZ = deskPos[2];
      targetFaceRot = deskRotation;
      currentPos.current.x = deskPos[0];
      currentPos.current.z = deskPos[2];
      currentRot.current = deskRotation;
    }

    const hasWaypoints = !isHardLocked && activeWaypoints.length > 0 && waypointIndex < activeWaypoints.length;

    if (hasWaypoints) {
      const currentWP = activeWaypoints[waypointIndex];
      targetX = currentWP[0];
      targetZ = currentWP[1];

      const dx = targetX - currentPos.current.x;
      const dz = targetZ - currentPos.current.z;
      const dist = Math.sqrt(dx * dx + dz * dz);

      // Advance to next waypoint if reached within 0.28 units (adjusted for high-speed walking)
      if (dist < 0.28) {
        if (waypointIndex < activeWaypoints.length - 1) {
          setWaypointIndex(waypointIndex + 1);
        } else {
          setActiveWaypoints([]);
        }
      }
    } else if (!isHardLocked) {
      // Steady state destination
      if (isMeeting) {
        targetX = meetingPos[0];
        targetZ = meetingPos[2];
        targetFaceRot = Math.atan2(0 - meetingPos[0], 3.5 - meetingPos[2]);
      } else if (isQuarantined) {
        targetX = quarantinePos[0];
        targetZ = quarantinePos[2];
        targetFaceRot = quarantineFacingRot ?? 0;
      } else if (activeMission === 'DOMINO_PHASE_5' && isAuditorAgent) {
        // Paused in front of Sector 1 operators briefing facing west towards them
        targetX = room1Briefing[0];
        targetZ = room1Briefing[1];
        targetFaceRot = -Math.PI / 2;
      } else if (activeMission === 'DOMINO_PHASE_1' && isNewsAgent) {
        // Paused directly in front of Auditor Quant desk facing east towards Auditor
        targetX = 7.8;
        targetZ = 2.0;
        targetFaceRot = Math.PI / 2;
      } else {
        // STRICTLY AT DESK FACING MONITORS
        targetX = deskPos[0];
        targetZ = deskPos[2];
        targetFaceRot = deskRotation;
      }
    }

    const dx = targetX - currentPos.current.x;
    const dz = targetZ - currentPos.current.z;
    const dist = Math.sqrt(dx * dx + dz * dz);
    const isMoving = dist > 0.08;

    if (isMoving) {
      const isDomino = activeMission.startsWith('DOMINO') || activeMission === 'DELIVER_NEWS';
      const speedMult = isDomino ? 1.45 : (isMeeting || state === 'EXECUTING' ? 1.25 : 1.0);
      currentPos.current.x += dx * walkSeed.moveSpeed * speedMult;
      currentPos.current.z += dz * walkSeed.moveSpeed * speedMult;

      // Snappy rotation towards walking direction
      const walkAngle = Math.atan2(dx, dz);
      let angleDiff = walkAngle - currentRot.current;
      while (angleDiff > Math.PI) angleDiff -= Math.PI * 2;
      while (angleDiff < -Math.PI) angleDiff += Math.PI * 2;
      currentRot.current += angleDiff * 0.28;

      // Accelerated, energetic limb swing animation per agent
      const cycle = clock.elapsedTime * walkSeed.stepFreq + walkSeed.stepPhase;
      const swing = Math.sin(cycle) * walkSeed.swingAmp;
      if (leftLegRef.current) leftLegRef.current.rotation.x = swing;
      if (rightLegRef.current) rightLegRef.current.rotation.x = -swing;
      if (leftArmRef.current) leftArmRef.current.rotation.x = -swing;
      if (rightArmRef.current) rightArmRef.current.rotation.x = swing;

      groupRef.current.position.y = Math.abs(Math.sin(cycle)) * walkSeed.bobAmount;
    } else {
      // Arrived at destination: snap facing direction
      let angleDiff = targetFaceRot - currentRot.current;
      while (angleDiff > Math.PI) angleDiff -= Math.PI * 2;
      while (angleDiff < -Math.PI) angleDiff += Math.PI * 2;
      currentRot.current += angleDiff * 0.18;

      // Natural seated posture in chair when at desk or boardroom
      const isSeated = !isQuarantined && activeWaypoints.length === 0;
      if (isSeated) {
        // Thighs bent forward to sit on chair seat cushion
        if (leftLegRef.current) leftLegRef.current.rotation.x = -1.25;
        if (rightLegRef.current) rightLegRef.current.rotation.x = -1.25;
        groupRef.current.position.y = 0.18;
      } else {
        if (leftLegRef.current) leftLegRef.current.rotation.x = 0;
        if (rightLegRef.current) rightLegRef.current.rotation.x = 0;
        groupRef.current.position.y = 0;
      }

      // Fast typing motion if at desk in ANALYZING or EXECUTING
      if (!isMeeting && !isQuarantined && (state === 'EXECUTING' || state === 'ANALYZING')) {
        const typeSpeed = state === 'EXECUTING' ? 24 : 14;
        const leftType = Math.sin(clock.elapsedTime * typeSpeed + walkSeed.stepPhase) * 0.25 - 0.5;
        const rightType = Math.cos(clock.elapsedTime * typeSpeed + walkSeed.stepPhase) * 0.25 - 0.5;
        if (leftArmRef.current) leftArmRef.current.rotation.x = leftType;
        if (rightArmRef.current) rightArmRef.current.rotation.x = rightType;
      } else if (isMeeting) {
        // Hands resting forward on boardroom table
        const breath = Math.sin(clock.elapsedTime * 2.2 + walkSeed.stepPhase) * 0.03;
        if (leftArmRef.current) leftArmRef.current.rotation.x = -0.55 + breath;
        if (rightArmRef.current) rightArmRef.current.rotation.x = -0.55 + breath;
      } else {
        // Seated idle breathing
        const breath = Math.sin(clock.elapsedTime * 2.2 + walkSeed.stepPhase) * 0.04;
        if (leftArmRef.current) leftArmRef.current.rotation.x = breath;
        if (rightArmRef.current) rightArmRef.current.rotation.x = breath;
      }
    }

    // Apply transform
    groupRef.current.position.x = currentPos.current.x;
    groupRef.current.position.z = currentPos.current.z;
    groupRef.current.rotation.y = currentRot.current;

    // Visor glow
    if (visorRef.current) {
      const visorMat = visorRef.current.material as THREE.MeshStandardMaterial;
      if (state === 'EXECUTING') {
        visorMat.emissiveIntensity = Math.sin(clock.elapsedTime * 15) * 0.5 + 1.5;
      } else if (state === 'ANALYZING') {
        visorMat.emissiveIntensity = Math.sin(clock.elapsedTime * 8) * 0.4 + 1.1;
      } else if (isQuarantined) {
        visorMat.emissiveIntensity = 0.5;
      } else {
        visorMat.emissiveIntensity = 0.9;
      }
    }
  });

  const getStateBadge = () => {
    if (isQuarantined) {
      return {
        bg: 'bg-rose-500/30 text-rose-300 border-rose-500/60',
        icon: <Lock className="w-2.5 h-2.5 text-rose-400" />,
        label: 'QUARANTINED',
      };
    }
    if (isMeeting) {
      return {
        bg: 'bg-purple-500/30 text-purple-200 border-purple-400',
        icon: <Users className="w-2.5 h-2.5 text-purple-300 animate-pulse" />,
        label: 'IN MEETING',
      };
    }
    switch (state) {
      case 'ANALYZING':
        return {
          bg: 'bg-amber-500/30 text-amber-300 border-amber-500/60',
          icon: <Cpu className="w-2.5 h-2.5 text-amber-300 animate-spin" />,
          label: 'ANALYZING',
        };
      case 'EXECUTING':
        return {
          bg: 'bg-emerald-500/40 text-emerald-200 border-emerald-400 shadow-[0_0_8px_#10b981]',
          icon: <Zap className="w-2.5 h-2.5 text-emerald-300 animate-bounce" />,
          label: 'EXECUTING',
        };
      default:
        return {
          bg: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
          icon: <Activity className="w-2.5 h-2.5 text-blue-400" />,
          label: 'IDLE (SEATED)',
        };
    }
  };

  const [hovered, setHovered] = useState(false);

  // Dynamic Real Net PnL from trades_history (filtering strictly status === 'CLOSED')
  const agentPnL = useMemo(() => {
    // 1. Prioridade máxima: valor da coluna do Supabase (total_profit ou pnl)
    if (agent.total_profit !== undefined && agent.total_profit !== null && !isNaN(Number(agent.total_profit))) {
      return Number(agent.total_profit);
    }
    if (agent.pnl !== undefined && agent.pnl !== null && !isNaN(Number(agent.pnl))) {
      return Number(agent.pnl);
    }
    return getAgentNetPnL(trades, agent.agent_id);
  }, [trades, agent.agent_id, agent.total_profit, agent.pnl]);

  const pnlFormatting = useMemo(() => {
    return formatPnL(agentPnL);
  }, [agentPnL]);

  const getShortInfo = () => {
    let name = 'AGENTE';
    let pnl = 'IDLE';
    let pnlColor = 'text-cyan-400';
    let dotColor = 'bg-cyan-400';
    const isOps = agent.sector === 1 || agent.agent_id.startsWith('ops_');

    if (agent.agent_id.includes('alpha')) {
      name = 'ALPHA';
    } else if (agent.agent_id.includes('beta')) {
      name = 'BETA';
    } else if (agent.agent_id.includes('gamma')) {
      name = 'GAMMA';
    } else if (agent.agent_id.includes('delta')) {
      name = 'DELTA';
    } else if (agent.agent_id.includes('epsilon')) {
      name = 'EPSILON';
    } else if (agent.agent_id.includes('news')) {
      name = 'ORÁCULO';
      pnl = 'NOTÍCIAS';
      pnlColor = 'text-amber-400';
      dotColor = 'bg-amber-400';
    } else if (agent.agent_id.includes('auditor') || agent.agent_id.includes('analytics')) {
      name = 'AUDITOR';
      pnl = 'SHARPE';
      pnlColor = 'text-cyan-400';
      dotColor = 'bg-cyan-400';
    } else if (agent.agent_id.includes('rnd')) {
      name = 'P&D';
      pnl = 'MACHINE LEARNING';
      pnlColor = 'text-fuchsia-400';
      dotColor = 'bg-fuchsia-400';
    } else if (agent.agent_id.includes('cro') || agent.agent_id.includes('manager')) {
      name = 'DIRETOR CRO';
      pnl = 'RISCO';
      pnlColor = 'text-yellow-400';
      dotColor = 'bg-yellow-400';
    } else if (agent.agent_id.includes('boardroom')) {
      name = 'CONSELHO';
      pnl = isMeeting ? 'REUNIÃO' : 'IDLE';
      pnlColor = 'text-purple-400';
      dotColor = 'bg-purple-400';
    }

    // Para todos os agentes operadores, o Net PnL é OBRIGATÓRIO e prioritário na pílula 3D
    if (isOps) {
      // 1. Prioridade máxima: coluna total_profit ou pnl diretamente do Supabase no objeto agent
      const hasSupabasePnL = (agent.total_profit !== undefined && agent.total_profit !== null) ||
                             (agent.pnl !== undefined && agent.pnl !== null);
      const supabaseVal = agent.total_profit !== undefined && agent.total_profit !== null
        ? Number(agent.total_profit)
        : Number(agent.pnl ?? 0);

      const perf =
        agentPerformance?.[agent.agent_id] ||
        agentPerformance?.[agent.agent_id.replace(/^ops_/, '')] ||
        (agentPerformance ? Object.values(agentPerformance).find((p) => p.agentId === agent.agent_id) : null);

      if (hasSupabasePnL && !isNaN(supabaseVal)) {
        const fmt = formatPnL(supabaseVal);
        pnl = fmt.formatted;
        pnlColor = fmt.colorClass;
        dotColor = fmt.dotColorClass;
      } else if (perf && (perf.pnl !== 0 || perf.totalTrades > 0)) {
        pnl = perf.formattedPnL;
        pnlColor = perf.colorClass;
        dotColor = perf.dotColorClass;
      } else {
        pnl = pnlFormatting.formatted;
        pnlColor = pnlFormatting.colorClass;
        dotColor = pnlFormatting.dotColorClass;
      }
    } else {
      if (isMeeting) {
        pnl = 'REUNIÃO';
        pnlColor = 'text-purple-300';
        dotColor = 'bg-purple-400 animate-pulse';
      } else if (isQuarantined) {
        pnl = 'DESCANSO';
        pnlColor = 'text-rose-400';
        dotColor = 'bg-rose-500 animate-pulse';
      } else if (activeMission === 'DELIVER_NEWS' && agent.agent_id.includes('news')) {
        pnl = 'BRIEFING MACRO';
        pnlColor = 'text-amber-300';
        dotColor = 'bg-amber-400 animate-ping';
      } else if (activeMission === 'DELIVER_AUDIT' && (agent.agent_id.includes('auditor') || agent.agent_id.includes('analytics'))) {
        pnl = 'AUDITORIA QUANT';
        pnlColor = 'text-cyan-300';
        dotColor = 'bg-cyan-400 animate-ping';
      } else if (activeMission === 'INSTALL_CALIBRATION' && agent.agent_id.includes('rnd')) {
        pnl = 'CALIBRANDO STOPS';
        pnlColor = 'text-fuchsia-300';
        dotColor = 'bg-fuchsia-400 animate-ping';
      } else if (activeMission === 'CRO_DIRECTIVE' && (agent.agent_id.includes('cro') || agent.agent_id.includes('manager'))) {
        pnl = 'INSPEÇÃO DE RISCO';
        pnlColor = 'text-yellow-300';
        dotColor = 'bg-yellow-400 animate-ping';
      }
    }

    return { name, pnl, pnlColor, dotColor };
  };

  const short = getShortInfo();
  const rawThought = customThought || agent.last_thought || 'No posto operacional...';

  return (
    <group ref={groupRef}>
      {/* 3D Voxel Body (100% Opaque, depthWrite true) */}
      <group position={[0, 0, 0]}>
        {/* Left Leg */}
        <group ref={leftLegRef} position={[-0.12, 0.45, 0]}>
          <mesh position={[0, -0.22, 0]}>
            <boxGeometry args={[0.13, 0.44, 0.15]} />
            <meshStandardMaterial color="#090d16" roughness={0.5} />
          </mesh>
          <mesh position={[0, -0.42, 0.04]}>
            <boxGeometry args={[0.14, 0.08, 0.22]} />
            <meshStandardMaterial color="#1e293b" roughness={0.3} metalness={0.7} />
          </mesh>
        </group>

        {/* Right Leg */}
        <group ref={rightLegRef} position={[0.12, 0.45, 0]}>
          <mesh position={[0, -0.22, 0]}>
            <boxGeometry args={[0.13, 0.44, 0.15]} />
            <meshStandardMaterial color="#090d16" roughness={0.5} />
          </mesh>
          <mesh position={[0, -0.42, 0.04]}>
            <boxGeometry args={[0.14, 0.08, 0.22]} />
            <meshStandardMaterial color="#1e293b" roughness={0.3} metalness={0.7} />
          </mesh>
        </group>

        {/* Torso */}
        <mesh position={[0, 0.76, 0]}>
          <boxGeometry args={[0.42, 0.54, 0.24]} />
          <meshStandardMaterial color={roleColor} roughness={0.3} metalness={0.4} />
        </mesh>
        <mesh position={[0, 0.82, 0.125]}>
          <boxGeometry args={[0.18, 0.12, 0.01]} />
          <meshStandardMaterial color="#020617" emissive={visorColor} emissiveIntensity={0.6} />
        </mesh>

        {/* Left Arm */}
        <group ref={leftArmRef} position={[-0.28, 0.95, 0]}>
          <mesh position={[0, -0.22, 0]}>
            <boxGeometry args={[0.12, 0.48, 0.14]} />
            <meshStandardMaterial color={roleColor} roughness={0.4} />
          </mesh>
          <mesh position={[0, -0.48, 0]}>
            <boxGeometry args={[0.11, 0.1, 0.12]} />
            <meshStandardMaterial color="#fcd34d" roughness={0.5} />
          </mesh>
        </group>

        {/* Right Arm */}
        <group ref={rightArmRef} position={[0.28, 0.95, 0]}>
          <mesh position={[0, -0.22, 0]}>
            <boxGeometry args={[0.12, 0.48, 0.14]} />
            <meshStandardMaterial color={roleColor} roughness={0.4} />
          </mesh>
          <mesh position={[0, -0.48, 0]}>
            <boxGeometry args={[0.11, 0.1, 0.12]} />
            <meshStandardMaterial color="#fcd34d" roughness={0.5} />
          </mesh>
        </group>

        {/* Head */}
        <mesh position={[0, 1.25, 0]}>
          <boxGeometry args={[0.38, 0.38, 0.36]} />
          <meshStandardMaterial color="#0b0f19" roughness={0.2} metalness={0.6} />
        </mesh>

        {/* Visor */}
        <mesh ref={visorRef} position={[0, 1.27, 0.185]}>
          <boxGeometry args={[0.32, 0.12, 0.02]} />
          <meshStandardMaterial
            color="#020617"
            emissive={visorColor}
            emissiveIntensity={1.0}
            roughness={0.1}
          />
        </mesh>
      </group>

      {/* ========================================================= */}
      {/* 4. BALÃO DE FALA DINÂMICO (VISÍVEL DURANTE MISSÕES/DOMINÓ) */}
      {/* ========================================================= */}
      {customThought && (
        <Html
          position={[0, 2.50, 0]}
          center
          distanceFactor={14}
          zIndexRange={[30, 20]}
          style={{ pointerEvents: 'none' }}
        >
          <div className="flex flex-col items-center animate-in fade-in zoom-in-95 duration-150 select-none">
            <div className="px-3 py-1.5 rounded-2xl bg-slate-950/95 border-2 border-cyan-400 text-cyan-200 text-xs font-mono font-bold whitespace-nowrap shadow-[0_0_20px_rgba(6,182,212,0.6)] backdrop-blur-md flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
              <span>{customThought}</span>
            </div>
            <div className="w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[6px] border-t-cyan-400" />
          </div>
        </Html>
      )}

      {/* ========================================================= */}
      {/* 5. PÍLULA MINIMALISTA DE 1 LINHA (SEM TRANSFORM / OCCLUDE)*/}
      {/* ========================================================= */}
      <Html
        position={[0, 1.9, 0]}
        center
        distanceFactor={15}
        zIndexRange={[5, 0]}
        style={{ pointerEvents: 'auto' }}
      >
        <div
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          onClick={(e) => {
            e.stopPropagation();
            if (onSelectAgent) onSelectAgent(agent);
          }}
          className="relative cursor-pointer select-none group"
        >
          {/* 1-Line Compact Pill */}
          <div className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-slate-950/90 border border-slate-700/80 hover:border-cyan-400 text-[11px] font-mono font-bold whitespace-nowrap shadow-md backdrop-blur-sm transition-all hover:scale-105">
            <span className={`w-2 h-2 rounded-full ${short.dotColor}`} />
            <span className="text-slate-100">• {short.name}</span>
            <span className={short.pnlColor}>{short.pnl}</span>
            {isQuarantined && (
              <span className="text-[9px] text-rose-400 bg-rose-950/80 px-1 rounded border border-rose-500/50">
                QUARANTINE
              </span>
            )}
            {!isQuarantined && isImmunized && (
              <span className="text-[9px] text-emerald-300 bg-emerald-950/80 px-1 rounded border border-emerald-500/50 shadow-[0_0_6px_#10b981]">
                🛡️ IMUNE
              </span>
            )}
            {!isQuarantined && agent.allocation_weight !== undefined && agent.allocation_weight !== 1.0 && (
              <span className="text-[9px] text-yellow-400 bg-yellow-950/60 px-1 rounded border border-yellow-500/40">
                {agent.allocation_weight}x
              </span>
            )}
          </div>

          {/* Tooltip on Hover */}
          {hovered && (
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-44 p-2 rounded-xl bg-slate-950/95 border border-slate-700 shadow-2xl text-[9px] font-sans text-slate-200 pointer-events-none z-50 animate-in fade-in duration-100">
              <div className="text-[8px] font-mono text-cyan-400 uppercase tracking-wider font-bold mb-0.5">
                {agent.name}
              </div>
              <p className="line-clamp-3 leading-tight text-slate-300">
                "{rawThought}"
              </p>
            </div>
          )}
        </div>
      </Html>
    </group>
  );
};

