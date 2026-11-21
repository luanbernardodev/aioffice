'use client';

import React, { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { AgentStatus, Trade } from '@/types';
import { CloseEvent } from '@/hooks/useOffice';
import { GROUP_STYLE, groupOf, shortName, fmtUsd } from './layout';

interface TraderProps {
  agent: AgentStatus;
  position: [number, number, number];
  zoneColor: string;
  rank: number;
  compPnl: number;
  open?: Trade;
  lastEvent?: CloseEvent;
  selected: boolean;
  onSelect: (a: AgentStatus) => void;
}

const EVENT_MS = 7000;

/** Mesa + cadeira + personagem voxel + plaquinha acima da cabeça. */
export function Trader({ agent, position, zoneColor, rank, compPnl, open, lastEvent, selected, onSelect }: TraderProps) {
  const group = groupOf(agent.agent_id);
  const style = GROUP_STYLE[group];
  const body = useRef<THREE.Group>(null);
  const armL = useRef<THREE.Mesh>(null);
  const armR = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.Mesh>(null);
  const screen = useRef<THREE.MeshStandardMaterial>(null);
  const seed = useMemo(() => [...agent.agent_id].reduce((s, c) => s + c.charCodeAt(0), 0) % 100, [agent.agent_id]);

  const openPnl = open ? Number(open.profit_usd) || 0 : 0;
  const screenColor = open ? (openPnl >= 0 ? '#22c55e' : '#ef4444') : zoneColor;
  const eventLive = lastEvent && Date.now() - lastEvent.at < EVENT_MS;
  const eventColor = lastEvent && lastEvent.profit >= 0 ? '#22c55e' : '#ef4444';
  const lastPnl = Number(agent.pnl) || 0;

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime() + seed;
    if (body.current) body.current.position.y = Math.sin(t * 1.6) * 0.015;
    const typing = open ? 1 : 0.25;
    if (armL.current) armL.current.rotation.x = -1.1 + Math.sin(t * 14) * 0.12 * typing;
    if (armR.current) armR.current.rotation.x = -1.1 + Math.cos(t * 13) * 0.12 * typing;
    if (screen.current) screen.current.emissiveIntensity = open ? 1.6 + Math.sin(t * 4) * 0.5 : 0.9;
    if (ring.current) {
      const age = lastEvent ? (Date.now() - lastEvent.at) / EVENT_MS : 1;
      const alive = age < 1;
      ring.current.visible = alive;
      if (alive) {
        const s = 0.6 + age * 3.2;
        ring.current.scale.set(s, s, s);
        (ring.current.material as THREE.MeshBasicMaterial).opacity = (1 - age) * 0.7;
      }
    }
  });

  return (
    <group position={position}>
      {/* onda no chão quando fecha uma posição */}
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0.3]} visible={false}>
        <ringGeometry args={[0.55, 0.7, 48]} />
        <meshBasicMaterial color={eventColor} transparent opacity={0} />
      </mesh>

      {/* seleção */}
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.025, 0.3]}>
          <ringGeometry args={[1.25, 1.35, 64]} />
          <meshBasicMaterial color="#e2e8f0" transparent opacity={0.8} />
        </mesh>
      )}

      <group
        rotation={[0, Math.PI, 0]}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(agent);
        }}
        onPointerOver={() => (document.body.style.cursor = 'pointer')}
        onPointerOut={() => (document.body.style.cursor = 'auto')}
      >
        {/* mesa */}
        <mesh position={[0, 0.76, 0.35]} castShadow receiveShadow>
          <boxGeometry args={[2.2, 0.07, 1.0]} />
          <meshStandardMaterial color="#1f2937" roughness={0.35} metalness={0.4} />
        </mesh>
        <mesh position={[0, 0.79, 0.86]}>
          <boxGeometry args={[2.2, 0.012, 0.02]} />
          <meshStandardMaterial color={zoneColor} emissive={zoneColor} emissiveIntensity={1.4} />
        </mesh>
        {[-0.98, 0.98].map((x) => (
          <mesh key={x} position={[x, 0.38, 0.35]} castShadow>
            <boxGeometry args={[0.06, 0.76, 0.85]} />
            <meshStandardMaterial color="#0f172a" metalness={0.7} roughness={0.3} />
          </mesh>
        ))}
        {/* monitores (cor = estado: aberta no lucro/prejuízo, ou cor da ala) */}
        {[-0.48, 0.48].map((x, i) => (
          <group key={x} position={[x, 1.12, 0.62]} rotation={[0, x < 0 ? 0.18 : -0.18, 0]}>
            <mesh castShadow>
              <boxGeometry args={[0.86, 0.52, 0.04]} />
              <meshStandardMaterial color="#0b1220" />
            </mesh>
            <mesh position={[0, 0, -0.022]}>
              <planeGeometry args={[0.8, 0.46]} />
              <meshStandardMaterial
                ref={i === 0 ? screen : undefined}
                color={screenColor}
                emissive={screenColor}
                emissiveIntensity={0.9}
                side={THREE.DoubleSide}
              />
            </mesh>
            <mesh position={[0, -0.34, 0]}>
              <boxGeometry args={[0.05, 0.18, 0.05]} />
              <meshStandardMaterial color="#111827" />
            </mesh>
          </group>
        ))}
        {/* cadeira */}
        <mesh position={[0, 0.48, -0.55]} castShadow>
          <boxGeometry args={[0.62, 0.08, 0.6]} />
          <meshStandardMaterial color="#111827" roughness={0.6} />
        </mesh>
        <mesh position={[0, 0.85, -0.83]} castShadow>
          <boxGeometry args={[0.62, 0.72, 0.08]} />
          <meshStandardMaterial color="#111827" roughness={0.6} />
        </mesh>
        <mesh position={[0, 0.24, -0.55]}>
          <cylinderGeometry args={[0.04, 0.04, 0.44, 10]} />
          <meshStandardMaterial color="#334155" metalness={0.8} />
        </mesh>

        {/* personagem voxel (de frente para a mesa) */}
        <group ref={body} position={[0, 0, -0.5]}>
          <mesh position={[-0.13, 0.62, 0.22]} rotation={[-1.45, 0, 0]} castShadow>
            <boxGeometry args={[0.16, 0.42, 0.16]} />
            <meshStandardMaterial color="#1e293b" />
          </mesh>
          <mesh position={[0.13, 0.62, 0.22]} rotation={[-1.45, 0, 0]} castShadow>
            <boxGeometry args={[0.16, 0.42, 0.16]} />
            <meshStandardMaterial color="#1e293b" />
          </mesh>
          <mesh position={[0, 0.98, 0]} castShadow>
            <boxGeometry args={[0.5, 0.6, 0.3]} />
            <meshStandardMaterial color={style.shirt} roughness={0.55} />
          </mesh>
          <mesh position={[0, 1.02, 0.155]}>
            <boxGeometry args={[0.08, 0.42, 0.01]} />
            <meshStandardMaterial color={zoneColor} emissive={zoneColor} emissiveIntensity={0.6} />
          </mesh>
          <mesh ref={armL} position={[-0.32, 1.12, 0.05]} castShadow>
            <boxGeometry args={[0.13, 0.5, 0.13]} />
            <meshStandardMaterial color={style.shirt} />
          </mesh>
          <mesh ref={armR} position={[0.32, 1.12, 0.05]} castShadow>
            <boxGeometry args={[0.13, 0.5, 0.13]} />
            <meshStandardMaterial color={style.shirt} />
          </mesh>
          <mesh position={[0, 1.48, 0]} castShadow>
            <boxGeometry args={[0.38, 0.38, 0.36]} />
            <meshStandardMaterial color="#f1c7a3" roughness={0.7} />
          </mesh>
          <mesh position={[0, 1.7, -0.02]}>
            <boxGeometry args={[0.4, 0.1, 0.38]} />
            <meshStandardMaterial color={seed % 3 === 0 ? '#2b1d14' : seed % 3 === 1 ? '#111827' : '#6b4f2a'} />
          </mesh>
          {open && (
            <mesh position={[0.26, 1.92, 0]}>
              <sphereGeometry args={[0.07, 14, 14]} />
              <meshStandardMaterial color={screenColor} emissive={screenColor} emissiveIntensity={2.5} />
            </mesh>
          )}
        </group>
      </group>

      {/* plaquinha acima da cabeça */}
      <Html position={[0, 2.6, 0.5]} center distanceFactor={13} zIndexRange={[8, 0]} style={{ pointerEvents: 'none' }}>
        <div className="flex flex-col items-center select-none">
          {eventLive && lastEvent && (
            <div
              key={lastEvent.id + lastEvent.at}
              className={`mb-1 px-2.5 py-1 rounded-lg text-[15px] font-black tracking-tight shadow-lg animate-[popup_7s_ease-out_forwards] ${
                lastEvent.profit >= 0 ? 'bg-emerald-500 text-emerald-950' : 'bg-rose-500 text-rose-950'
              }`}
            >
              {fmtUsd(lastEvent.profit)}
            </div>
          )}
          <div
            className={`min-w-[132px] rounded-xl px-2.5 py-1.5 backdrop-blur-md ring-1 shadow-[0_8px_24px_rgba(0,0,0,0.45)] ${
              selected ? 'bg-slate-900/95 ring-white/60' : 'bg-slate-950/80 ring-white/10'
            } ${eventLive ? (lastEvent!.profit >= 0 ? 'ring-emerald-400' : 'ring-rose-400') : ''}`}
          >
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-black text-slate-950 rounded px-1 py-[1px]" style={{ background: zoneColor }}>
                #{rank || '–'}
              </span>
              <span className="text-[11px] font-bold text-slate-100 whitespace-nowrap">{shortName(agent.agent_id)}</span>
            </div>
            <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px] font-mono">
              <span className={compPnl > 0 ? 'text-emerald-300' : compPnl < 0 ? 'text-rose-300' : 'text-slate-400'}>
                comp {fmtUsd(compPnl)}
              </span>
              {open ? (
                <span className={openPnl >= 0 ? 'text-emerald-300' : 'text-rose-300'}>● {fmtUsd(openPnl)}</span>
              ) : (
                <span className={lastPnl > 0 ? 'text-emerald-400/80' : lastPnl < 0 ? 'text-rose-400/80' : 'text-slate-500'}>
                  últ {fmtUsd(lastPnl)}
                </span>
              )}
            </div>
          </div>
        </div>
      </Html>
    </group>
  );
}
