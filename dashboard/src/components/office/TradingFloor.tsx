'use client';

import React, { useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { ContactShadows, Html, OrbitControls } from '@react-three/drei';
import { AgentStatus, Trade } from '@/types';
import { CloseEvent, Competition } from '@/hooks/useOffice';
import { Trader } from './Trader';
import * as THREE from 'three';
import { ZONES, Zone, seatAgents, zoneRect, fmtUsd } from './layout';

interface FloorProps {
  agents: AgentStatus[];
  stats: Record<string, { open?: Trade }>;
  competition: Competition | null;
  events: CloseEvent[];
  selectedId: string | null;
  onSelect: (a: AgentStatus | null) => void;
}

function Plant({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh position={[0, 0.3, 0]} castShadow>
        <cylinderGeometry args={[0.28, 0.22, 0.6, 16]} />
        <meshStandardMaterial color="#e5e7eb" roughness={0.8} />
      </mesh>
      {[0, 1, 2, 3, 4].map((i) => (
        <mesh key={i} position={[Math.sin(i * 1.3) * 0.18, 0.85 + (i % 2) * 0.22, Math.cos(i * 1.3) * 0.18]} castShadow>
          <sphereGeometry args={[0.26 - i * 0.02, 12, 12]} />
          <meshStandardMaterial color={i % 2 ? '#15803d' : '#16a34a'} roughness={0.9} />
        </mesh>
      ))}
    </group>
  );
}

function Rack({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh position={[0, 1.1, 0]} castShadow>
        <boxGeometry args={[0.9, 2.2, 0.8]} />
        <meshStandardMaterial color="#0b1220" metalness={0.6} roughness={0.35} />
      </mesh>
      {Array.from({ length: 9 }).map((_, i) => (
        <mesh key={i} position={[0, 0.25 + i * 0.22, 0.41]}>
          <boxGeometry args={[0.7, 0.04, 0.01]} />
          <meshStandardMaterial
            color={i % 3 === 0 ? '#22d3ee' : '#22c55e'}
            emissive={i % 3 === 0 ? '#22d3ee' : '#22c55e'}
            emissiveIntensity={1.6}
          />
        </mesh>
      ))}
    </group>
  );
}

function ScoreWall({ competition }: { competition: Competition | null }) {
  // desenhado em textura (canvas): o <Html> da drei falha no primeiro elemento HTML da cena
  const texture = useMemo(() => {
    const c = document.createElement('canvas');
    c.width = 1200;
    c.height = 520;
    const g = c.getContext('2d')!;
    const grd = g.createLinearGradient(0, 0, 0, 520);
    grd.addColorStop(0, '#08101f');
    grd.addColorStop(1, '#050811');
    g.fillStyle = grd;
    g.fillRect(0, 0, 1200, 520);
    g.textAlign = 'center';
    g.fillStyle = '#7dd3fc';
    g.font = '600 26px ui-monospace, Consolas, monospace';
    g.fillText('C O M P E T I Ç Ã O   ·   A N T I G O S   ×   N O V O S', 600, 52);
    const tot = competition?.total_por_grupo;
    const col = (v: number) => (v > 0 ? '#6ee7b7' : v < 0 ? '#fda4af' : '#94a3b8');
    g.font = '900 78px ui-monospace, Consolas, monospace';
    g.fillStyle = col(tot?.antigo || 0);
    g.textAlign = 'right';
    g.fillText(fmtUsd(tot?.antigo), 540, 150);
    g.fillStyle = '#64748b';
    g.textAlign = 'center';
    g.font = '700 48px ui-monospace, Consolas, monospace';
    g.fillText('×', 600, 146);
    g.font = '900 78px ui-monospace, Consolas, monospace';
    g.fillStyle = col(tot?.novo || 0);
    g.textAlign = 'left';
    g.fillText(fmtUsd(tot?.novo), 660, 150);
    g.font = '600 30px ui-monospace, Consolas, monospace';
    (competition?.placar || []).slice(0, 6).forEach((r, i) => {
      const y = 220 + i * 48;
      g.fillStyle = 'rgba(255,255,255,0.05)';
      g.fillRect(110, y - 34, 980, 44);
      g.textAlign = 'left';
      g.fillStyle = '#cbd5e1';
      g.fillText(`${i + 1}. ${r.agente}`, 130, y);
      g.fillStyle = '#64748b';
      g.fillText(r.grupo, 700, y);
      g.textAlign = 'right';
      g.fillStyle = col(r.pnl);
      g.fillText(`${fmtUsd(r.pnl)} · ${r.trades}t`, 1070, y);
    });
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
  }, [competition]);
  return (
    <group position={[-1, 0, -8.9]}>
      <mesh position={[0, 3.1, 0]}>
        <boxGeometry args={[9.6, 4.2, 0.15]} />
        <meshStandardMaterial color="#05080f" metalness={0.5} roughness={0.4} />
      </mesh>
      <mesh position={[0, 3.1, 0.08]}>
        <boxGeometry args={[9.8, 4.4, 0.02]} />
        <meshStandardMaterial color="#38bdf8" emissive="#38bdf8" emissiveIntensity={0.6} transparent opacity={0.25} />
      </mesh>
      <mesh position={[0, 3.1, 0.1]}>
        <planeGeometry args={[9.4, 4.07]} />
        <meshBasicMaterial map={texture} toneMapped={false} />
      </mesh>
    </group>
  );
}

function ZoneSign({ zone, count, position }: { zone: Zone; count: number; position: [number, number, number] }) {
  const texture = useMemo(() => {
    const c = document.createElement('canvas');
    c.width = 1024;
    c.height = 160;
    const g = c.getContext('2d')!;
    g.fillStyle = `${zone.color}22`;
    g.strokeStyle = zone.color;
    g.lineWidth = 4;
    g.beginPath();
    g.roundRect(4, 4, 1016, 152, 26);
    g.fill();
    g.stroke();
    g.fillStyle = zone.color;
    g.font = '900 86px system-ui, Segoe UI, sans-serif';
    g.textBaseline = 'middle';
    g.fillText(zone.label.split('').join(String.fromCharCode(8202)), 34, 84);
    const w = g.measureText(zone.label.split('').join(String.fromCharCode(8202))).width;
    g.fillStyle = '#cbd5e1';
    g.font = '600 34px system-ui, Segoe UI, sans-serif';
    g.fillText(`${zone.sub.toUpperCase()}  ·  ${count} AGENTES`, 34 + w + 34, 88);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
  }, [zone, count]);
  return (
    <mesh position={position} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[4.6, 0.72]} />
      <meshBasicMaterial map={texture} transparent toneMapped={false} />
    </mesh>
  );
}

export default function TradingFloor({ agents, stats, competition, events, selectedId, onSelect }: FloorProps) {
  const seats = useMemo(() => seatAgents(agents), [agents]);
  const ranks = useMemo(() => {
    const m: Record<string, { rank: number; pnl: number }> = {};
    (competition?.placar || []).forEach((r, i) => (m[r.agente] = { rank: i + 1, pnl: r.pnl }));
    return m;
  }, [competition]);
  const lastEvent = useMemo(() => {
    const m: Record<string, CloseEvent> = {};
    for (const e of events) if (!m[e.agentId]) m[e.agentId] = e;
    return m;
  }, [events]);

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [1.6, 21, 22.5], fov: 42 }}
      onPointerMissed={() => onSelect(null)}
      className="!absolute inset-0"
    >
      {/* Rótulo vazio e invisível: nesta versão da drei o PRIMEIRO <Html> da cena não chega a aparecer
          (visto no GOLD, depois no placar e depois na plaquinha do Goldnight). Este absorve a falha. */}
      <Html position={[0, -100, 0]} style={{ display: 'none' }}>
        <span />
      </Html>
      <color attach="background" args={['#070a12']} />
      <fog attach="fog" args={['#070a12', 32, 62]} />
      <ambientLight intensity={0.45} />
      <hemisphereLight args={['#c7d2fe', '#0b0f19', 0.45]} />
      <directionalLight
        position={[10, 18, 12]}
        intensity={1.25}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-24}
        shadow-camera-right={24}
        shadow-camera-top={16}
        shadow-camera-bottom={-16}
      />

      {/* piso e paredes */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow position={[0, 0, 0]}>
        <planeGeometry args={[46, 22]} />
        <meshStandardMaterial color="#111827" roughness={0.55} metalness={0.25} />
      </mesh>
      <gridHelper args={[46, 46, '#1f2a3f', '#151d2d']} position={[0, 0.005, 0]} />
      <mesh position={[0, 3, -9.05]} receiveShadow>
        <boxGeometry args={[46, 6, 0.2]} />
        <meshStandardMaterial color="#0d1424" roughness={0.8} />
      </mesh>
      <mesh position={[-23, 3, 0]} receiveShadow>
        <boxGeometry args={[0.2, 6, 22]} />
        <meshStandardMaterial color="#0d1424" roughness={0.8} />
      </mesh>
      {[-14, -6, 6, 14].map((x) => (
        <mesh key={x} position={[x, 5.7, -8.9]}>
          <boxGeometry args={[4, 0.06, 0.1]} />
          <meshStandardMaterial color="#e0f2fe" emissive="#e0f2fe" emissiveIntensity={1.4} />
        </mesh>
      ))}

      {/* alas: tapete colorido, luz e placa */}
      {ZONES.map((z) => {
        const n = seats.filter((s) => s.zone.key === z.key).length;
        if (!n) return null;
        const r = zoneRect(z, n);
        return (
          <group key={z.key}>
            <mesh rotation={[-Math.PI / 2, 0, 0]} position={[r.cx, 0.012, r.cz]} receiveShadow>
              <planeGeometry args={[r.w, r.d]} />
              <meshStandardMaterial color={z.color} transparent opacity={0.07} />
            </mesh>
            {[[0, -r.d / 2, r.w, 0.05], [0, r.d / 2, r.w, 0.05], [-r.w / 2, 0, 0.05, r.d], [r.w / 2, 0, 0.05, r.d]].map(
              ([dx, dz, w, d], i) => (
                <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[r.cx + dx, 0.016, r.cz + dz]}>
                  <planeGeometry args={[w, d]} />
                  <meshStandardMaterial color={z.color} emissive={z.color} emissiveIntensity={0.9} transparent opacity={0.55} />
                </mesh>
              ),
            )}
            <pointLight position={[r.cx, 4.2, r.cz]} intensity={14} distance={11} color={z.color} />
          </group>
        );
      })}

      {/* placas das alas: textura de texto em 3D (sem DOM), inclinadas para a câmera */}
      {ZONES.map((z) => {
        const n = seats.filter((s) => s.zone.key === z.key).length;
        if (!n) return null;
        const r = zoneRect(z, n);
        return <ZoneSign key={`placa-${z.key}`} zone={z} count={n} position={[r.cx - r.w / 2 + 2.3, 0.02, r.cz + r.d / 2 + 0.55]} />;
      })}

      <ScoreWall competition={competition} />
      <Rack position={[-21.6, 0, -7.6]} />
      <Rack position={[-20.4, 0, -7.6]} />
      <Plant position={[-21.8, 0, 8.4]} />
      <Plant position={[19.5, 0, -7.8]} />
      <Plant position={[19.5, 0, 8.4]} />
      <Plant position={[-6.4, 0, -7.8]} />

      {seats.map((s) => (
        <Trader
          key={s.agent.agent_id}
          agent={s.agent}
          position={s.pos}
          zoneColor={s.zone.color}
          rank={ranks[s.agent.agent_id]?.rank ?? Number(s.agent.allocation_weight) ?? 0}
          compPnl={ranks[s.agent.agent_id]?.pnl ?? Number(s.agent.total_profit) ?? 0}
          open={stats[s.agent.agent_id]?.open}
          lastEvent={lastEvent[s.agent.agent_id]}
          selected={selectedId === s.agent.agent_id}
          onSelect={onSelect}
        />
      ))}

      <ContactShadows position={[0, 0.01, 0]} opacity={0.35} scale={46} blur={2.4} far={6} />
      <OrbitControls
        target={[1.6, 0, -0.2]}
        maxPolarAngle={Math.PI / 2.35}
        minDistance={10}
        maxDistance={42}
        enableDamping
        dampingFactor={0.08}
      />
    </Canvas>
  );
}
