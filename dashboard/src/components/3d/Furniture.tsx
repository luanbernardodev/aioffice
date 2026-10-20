'use client';

import React, { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

// -------------------------------------------------------------
// Monitor with glowing screen showing trading mini-charts
// -------------------------------------------------------------
interface MonitorProps {
  position: [number, number, number];
  rotation?: [number, number, number];
  screenColor?: string;
  isExecuting?: boolean;
}

export const DeskMonitor: React.FC<MonitorProps> = ({
  position,
  rotation = [0, 0, 0],
  screenColor = '#10b981',
  isExecuting = false,
}) => {
  const screenRef = useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    if (screenRef.current && isExecuting) {
      const pulse = Math.sin(clock.elapsedTime * 12) * 0.3 + 0.8;
      (screenRef.current.material as THREE.MeshStandardMaterial).emissiveIntensity = 1.4 * pulse;
    }
  });

  return (
    <group position={position} rotation={rotation}>
      {/* Stand Base */}
      <mesh position={[0, 0.04, 0]} castShadow>
        <boxGeometry args={[0.26, 0.03, 0.18]} />
        <meshStandardMaterial color="#0f172a" roughness={0.4} metalness={0.8} />
      </mesh>
      {/* Stand Arm */}
      <mesh position={[0, 0.28, -0.04]} castShadow>
        <cylinderGeometry args={[0.02, 0.02, 0.46, 8]} />
        <meshStandardMaterial color="#334155" metalness={0.9} />
      </mesh>
      {/* Screen Frame */}
      <mesh position={[0, 0.52, 0]} castShadow>
        <boxGeometry args={[0.85, 0.52, 0.04]} />
        <meshStandardMaterial color="#090d16" roughness={0.3} metalness={0.7} />
      </mesh>
      {/* Screen Display Face */}
      <mesh ref={screenRef} position={[0, 0.52, 0.025]}>
        <planeGeometry args={[0.80, 0.47]} />
        <meshStandardMaterial
          color="#030712"
          emissive={screenColor}
          emissiveIntensity={isExecuting ? 1.4 : 0.8}
          roughness={0.2}
        />
      </mesh>
    </group>
  );
};

// -------------------------------------------------------------
// Workstation Desk (Open Space Wall Street Quant Floor)
// Tabletop: #64748b, Base: #334155, Solid LED strip at base, 2 monitors, Mug
// -------------------------------------------------------------
interface WorkstationProps {
  position: [number, number, number];
  rotation?: [number, number, number];
  accentColor: string;
  stateColor?: string;
  isExecuting?: boolean;
  isQuarantined?: boolean;
  agentLabel: string;
}

export const Workstation: React.FC<WorkstationProps> = ({
  position,
  rotation = [0, 0, 0],
  accentColor,
  stateColor = '#10b981',
  isExecuting = false,
  isQuarantined = false,
}) => {
  return (
    <group position={position} rotation={rotation}>
      {/* 1. Solid LED Neon Base Line under the desk */}
      <mesh position={[0, 0.04, 0]}>
        <boxGeometry args={[2.24, 0.08, 1.04]} />
        <meshStandardMaterial
          color={isQuarantined ? '#ef4444' : accentColor}
          emissive={isQuarantined ? '#ef4444' : accentColor}
          emissiveIntensity={2.2}
          roughness={0.2}
        />
      </mesh>

      {/* 2. Metal Base & Legs (#334155 solid, 100% opaque) */}
      <mesh position={[-0.95, 0.38, 0]} castShadow>
        <boxGeometry args={[0.08, 0.70, 0.85]} />
        <meshStandardMaterial color="#334155" roughness={0.4} metalness={0.8} />
      </mesh>
      <mesh position={[0.95, 0.38, 0]} castShadow>
        <boxGeometry args={[0.08, 0.70, 0.85]} />
        <meshStandardMaterial color="#334155" roughness={0.4} metalness={0.8} />
      </mesh>
      <mesh position={[0, 0.45, -0.38]} castShadow>
        <boxGeometry args={[1.82, 0.40, 0.04]} />
        <meshStandardMaterial color="#1e293b" roughness={0.5} metalness={0.7} />
      </mesh>

      {/* 3. Desk Tabletop (#64748b Cinza-Claro/Grafite Fosco) */}
      <mesh position={[0, 0.74, 0]} castShadow receiveShadow>
        <boxGeometry args={[2.2, 0.08, 1.0]} />
        <meshStandardMaterial color="#64748b" roughness={0.5} metalness={0.3} />
      </mesh>

      {/* Tabletop Front Trim Line */}
      <mesh position={[0, 0.74, 0.505]}>
        <boxGeometry args={[2.18, 0.02, 0.015]} />
        <meshStandardMaterial
          color={isQuarantined ? '#ef4444' : accentColor}
          emissive={isQuarantined ? '#ef4444' : accentColor}
          emissiveIntensity={1.5}
        />
      </mesh>

      {/* 4. Keyboard & Desk Mat */}
      <mesh position={[0, 0.785, 0.16]}>
        <boxGeometry args={[0.65, 0.015, 0.26]} />
        <meshStandardMaterial color="#090d16" roughness={0.6} />
      </mesh>
      <mesh position={[-0.06, 0.795, 0.16]}>
        <boxGeometry args={[0.42, 0.01, 0.13]} />
        <meshStandardMaterial color="#1e293b" emissive={accentColor} emissiveIntensity={0.2} />
      </mesh>
      {/* Mouse */}
      <mesh position={[0.22, 0.795, 0.16]}>
        <boxGeometry args={[0.06, 0.012, 0.09]} />
        <meshStandardMaterial color="#334155" metalness={0.7} />
      </mesh>

      {/* 5. White Coffee Mug on desk */}
      <group position={[0.82, 0.78, 0.2]}>
        <mesh position={[0, 0.045, 0]} castShadow>
          <cylinderGeometry args={[0.038, 0.032, 0.09, 12]} />
          <meshStandardMaterial color="#f8fafc" roughness={0.2} />
        </mesh>
        <mesh position={[0.042, 0.045, 0]}>
          <torusGeometry args={[0.022, 0.007, 8, 12]} />
          <meshStandardMaterial color="#f8fafc" roughness={0.2} />
        </mesh>
      </group>

      {/* 6. Dual Professional Monitors (2 Screens: 1 straight, 1 angled) */}
      <DeskMonitor
        position={[-0.42, 0.78, -0.16]}
        rotation={[0, 0.18, 0]}
        screenColor={isQuarantined ? '#ef4444' : stateColor}
        isExecuting={isExecuting}
      />
      <DeskMonitor
        position={[0.42, 0.78, -0.16]}
        rotation={[0, -0.18, 0]}
        screenColor={isQuarantined ? '#ef4444' : (stateColor === '#10b981' ? '#38bdf8' : '#10b981')}
        isExecuting={isExecuting}
      />

      {/* 7. Executive Leather Chair */}
      <group position={[0, 0, 0.60]}>
        {/* Wheels Base */}
        <mesh position={[0, 0.08, 0]}>
          <cylinderGeometry args={[0.26, 0.26, 0.04, 5]} />
          <meshStandardMaterial color="#1e293b" metalness={0.9} />
        </mesh>
        {/* Piston */}
        <mesh position={[0, 0.26, 0]}>
          <cylinderGeometry args={[0.035, 0.035, 0.32, 8]} />
          <meshStandardMaterial color="#64748b" metalness={0.9} />
        </mesh>
        {/* Seat Cushion */}
        <mesh position={[0, 0.44, 0]} castShadow>
          <boxGeometry args={[0.54, 0.08, 0.50]} />
          <meshStandardMaterial color="#0f172a" roughness={0.4} />
        </mesh>
        {/* Backrest */}
        <mesh position={[0, 0.82, 0.22]} rotation={[-0.08, 0, 0]} castShadow>
          <boxGeometry args={[0.48, 0.72, 0.08]} />
          <meshStandardMaterial color="#0f172a" roughness={0.4} />
        </mesh>
        {/* Accent Stripe */}
        <mesh position={[0, 0.82, 0.265]} rotation={[-0.08, 0, 0]}>
          <boxGeometry args={[0.10, 0.64, 0.02]} />
          <meshStandardMaterial color={accentColor} emissive={accentColor} emissiveIntensity={0.6} />
        </mesh>
      </group>
    </group>
  );
};

// -------------------------------------------------------------
// WALL STREET BULL (Golden Bull Statue on Dark Pedestal)
// -------------------------------------------------------------
export const WallStreetBull: React.FC<{ position: [number, number, number] }> = ({ position }) => {
  return (
    <group position={position}>
      {/* 1. Dark Granite Pedestal */}
      <mesh position={[0, 0.3, 0]} castShadow receiveShadow>
        <boxGeometry args={[3.4, 0.6, 2.2]} />
        <meshStandardMaterial color="#0f172a" roughness={0.3} metalness={0.8} />
      </mesh>

      {/* Gold Trim around pedestal top */}
      <mesh position={[0, 0.61, 0]}>
        <boxGeometry args={[3.44, 0.04, 2.24]} />
        <meshStandardMaterial color="#eab308" emissive="#eab308" emissiveIntensity={1.8} />
      </mesh>

      {/* Plaque in Front */}
      <mesh position={[0, 0.3, 1.11]}>
        <planeGeometry args={[1.8, 0.25]} />
        <meshStandardMaterial color="#fbbf24" metalness={0.9} roughness={0.2} />
      </mesh>

      {/* 2. Low-Poly Golden Bull Body */}
      <group position={[0, 0.62, 0]}>
        {/* Bull Torso (Angled Muscular Box) */}
        <mesh position={[0, 0.75, -0.1]} rotation={[-0.15, 0, 0]} castShadow>
          <boxGeometry args={[1.4, 0.9, 1.8]} />
          <meshStandardMaterial color="#f59e0b" metalness={0.85} roughness={0.25} />
        </mesh>

        {/* Muscular Shoulders / Hump */}
        <mesh position={[0, 1.05, 0.35]} rotation={[-0.2, 0, 0]} castShadow>
          <boxGeometry args={[1.2, 0.8, 0.9]} />
          <meshStandardMaterial color="#fbbf24" metalness={0.9} roughness={0.2} />
        </mesh>

        {/* Bull Head (Lowered, Charging Pose) */}
        <mesh position={[0, 0.85, 1.05]} rotation={[0.3, 0, 0]} castShadow>
          <boxGeometry args={[0.7, 0.65, 0.7]} />
          <meshStandardMaterial color="#f59e0b" metalness={0.9} roughness={0.2} />
        </mesh>

        {/* Snout */}
        <mesh position={[0, 0.65, 1.42]} rotation={[0.3, 0, 0]} castShadow>
          <boxGeometry args={[0.45, 0.35, 0.35]} />
          <meshStandardMaterial color="#d97706" metalness={0.8} roughness={0.3} />
        </mesh>

        {/* Left Horn */}
        <mesh position={[-0.45, 1.25, 1.05]} rotation={[0.4, -0.3, -0.6]} castShadow>
          <cylinderGeometry args={[0.04, 0.09, 0.65, 8]} />
          <meshStandardMaterial color="#fef08a" metalness={0.95} roughness={0.1} />
        </mesh>

        {/* Right Horn */}
        <mesh position={[0.45, 1.25, 1.05]} rotation={[0.4, 0.3, 0.6]} castShadow>
          <cylinderGeometry args={[0.04, 0.09, 0.65, 8]} />
          <meshStandardMaterial color="#fef08a" metalness={0.95} roughness={0.1} />
        </mesh>

        {/* Front Left Leg */}
        <mesh position={[-0.55, 0.35, 0.55]} rotation={[-0.2, 0, 0]} castShadow>
          <boxGeometry args={[0.28, 0.7, 0.28]} />
          <meshStandardMaterial color="#d97706" metalness={0.85} roughness={0.3} />
        </mesh>

        {/* Front Right Leg */}
        <mesh position={[0.55, 0.35, 0.75]} rotation={[0.2, 0, 0]} castShadow>
          <boxGeometry args={[0.28, 0.7, 0.28]} />
          <meshStandardMaterial color="#d97706" metalness={0.85} roughness={0.3} />
        </mesh>

        {/* Back Left Leg */}
        <mesh position={[-0.55, 0.35, -0.75]} rotation={[0.15, 0, 0]} castShadow>
          <boxGeometry args={[0.28, 0.7, 0.28]} />
          <meshStandardMaterial color="#d97706" metalness={0.85} roughness={0.3} />
        </mesh>

        {/* Back Right Leg */}
        <mesh position={[0.55, 0.35, -0.65]} rotation={[-0.1, 0, 0]} castShadow>
          <boxGeometry args={[0.28, 0.7, 0.28]} />
          <meshStandardMaterial color="#d97706" metalness={0.85} roughness={0.3} />
        </mesh>

        {/* Bull Tail curving upwards */}
        <mesh position={[0, 0.95, -1.05]} rotation={[-0.8, 0, 0]}>
          <cylinderGeometry args={[0.03, 0.05, 0.55, 6]} />
          <meshStandardMaterial color="#f59e0b" metalness={0.9} />
        </mesh>
      </group>
    </group>
  );
};

// -------------------------------------------------------------
// FRONT RAILING / GUARDA-CORPO (Varanda Frontal)
// Along the front edge with glowing yellow neon rail
// -------------------------------------------------------------
export const FrontRailing: React.FC<{ zPos?: number }> = ({ zPos = 17.5 }) => {
  const posts = [-20, -16, -12, -8, -4, 4, 8, 12, 16, 20];

  return (
    <group position={[0, 0, zPos]}>
      {/* Top Yellow Neon Handrail */}
      <mesh position={[0, 0.9, 0]}>
        <boxGeometry args={[42.0, 0.06, 0.06]} />
        <meshStandardMaterial color="#eab308" emissive="#eab308" emissiveIntensity={2.0} />
      </mesh>

      {/* Mid Rail */}
      <mesh position={[0, 0.5, 0]}>
        <boxGeometry args={[42.0, 0.04, 0.04]} />
        <meshStandardMaterial color="#334155" metalness={0.8} />
      </mesh>

      {/* Baseboard Curb */}
      <mesh position={[0, 0.08, 0]}>
        <boxGeometry args={[42.0, 0.16, 0.12]} />
        <meshStandardMaterial color="#1e293b" metalness={0.6} />
      </mesh>

      {/* Vertical Metal Posts */}
      {posts.map((x) => (
        <mesh key={x} position={[x, 0.45, 0]} castShadow>
          <boxGeometry args={[0.08, 0.9, 0.08]} />
          <meshStandardMaterial color="#0f172a" roughness={0.3} metalness={0.8} />
        </mesh>
      ))}
    </group>
  );
};

// -------------------------------------------------------------
// BILLIARDS / POOL TABLE (Lounge / Break Area)
// -------------------------------------------------------------
export const BilliardsTable: React.FC<{ position: [number, number, number]; rotation?: [number, number, number] }> = ({
  position,
  rotation = [0, 0, 0],
}) => {
  return (
    <group position={position} rotation={rotation}>
      {/* Green Felt Surface */}
      <mesh position={[0, 0.85, 0]} receiveShadow>
        <boxGeometry args={[3.2, 0.08, 1.8]} />
        <meshStandardMaterial color="#065f46" roughness={0.8} />
      </mesh>

      {/* Wooden Table Rails */}
      <mesh position={[0, 0.88, -0.92]}>
        <boxGeometry args={[3.36, 0.12, 0.08]} />
        <meshStandardMaterial color="#451a03" roughness={0.4} />
      </mesh>
      <mesh position={[0, 0.88, 0.92]}>
        <boxGeometry args={[3.36, 0.12, 0.08]} />
        <meshStandardMaterial color="#451a03" roughness={0.4} />
      </mesh>
      <mesh position={[-1.62, 0.88, 0]}>
        <boxGeometry args={[0.08, 0.12, 1.84]} />
        <meshStandardMaterial color="#451a03" roughness={0.4} />
      </mesh>
      <mesh position={[1.62, 0.88, 0]}>
        <boxGeometry args={[0.08, 0.12, 1.84]} />
        <meshStandardMaterial color="#451a03" roughness={0.4} />
      </mesh>

      {/* 4 Sturdy Legs */}
      <mesh position={[-1.4, 0.42, -0.75]} castShadow>
        <cylinderGeometry args={[0.10, 0.08, 0.84, 8]} />
        <meshStandardMaterial color="#291305" roughness={0.5} />
      </mesh>
      <mesh position={[1.4, 0.42, -0.75]} castShadow>
        <cylinderGeometry args={[0.10, 0.08, 0.84, 8]} />
        <meshStandardMaterial color="#291305" roughness={0.5} />
      </mesh>
      <mesh position={[-1.4, 0.42, 0.75]} castShadow>
        <cylinderGeometry args={[0.10, 0.08, 0.84, 8]} />
        <meshStandardMaterial color="#291305" roughness={0.5} />
      </mesh>
      <mesh position={[1.4, 0.42, 0.75]} castShadow>
        <cylinderGeometry args={[0.10, 0.08, 0.84, 8]} />
        <meshStandardMaterial color="#291305" roughness={0.5} />
      </mesh>

      {/* White Cue Ball */}
      <mesh position={[-0.8, 0.92, 0]}>
        <sphereGeometry args={[0.04, 12, 12]} />
        <meshStandardMaterial color="#f8fafc" roughness={0.1} />
      </mesh>
      {/* Red & Gold Balls cluster */}
      <mesh position={[0.7, 0.92, 0]}>
        <sphereGeometry args={[0.04, 12, 12]} />
        <meshStandardMaterial color="#ef4444" roughness={0.1} />
      </mesh>
      <mesh position={[0.78, 0.92, 0.04]}>
        <sphereGeometry args={[0.04, 12, 12]} />
        <meshStandardMaterial color="#eab308" roughness={0.1} />
      </mesh>
    </group>
  );
};

// -------------------------------------------------------------
// Water Cooler (Dispenser)
// -------------------------------------------------------------
export const WaterCooler: React.FC<{ position: [number, number, number] }> = ({ position }) => {
  return (
    <group position={position}>
      {/* White Stand Base */}
      <mesh position={[0, 0.55, 0]} castShadow>
        <boxGeometry args={[0.42, 1.1, 0.42]} />
        <meshStandardMaterial color="#e2e8f0" roughness={0.3} />
      </mesh>
      {/* Cyan Water Bottle on Top */}
      <mesh position={[0, 1.35, 0]} castShadow>
        <cylinderGeometry args={[0.18, 0.18, 0.45, 16]} />
        <meshStandardMaterial color="#0284c7" emissive="#0284c7" emissiveIntensity={0.5} roughness={0.1} />
      </mesh>
    </group>
  );
};

// -------------------------------------------------------------
// -------------------------------------------------------------
// Crisis Boardroom Conference Table (Wall Street Rectangular Table)
// -------------------------------------------------------------
export const CrisisBoardroomTable: React.FC<{
  position: [number, number, number];
  isMeetingActive?: boolean;
}> = ({ position, isMeetingActive = false }) => {
  return (
    <group position={position}>
      {/* 1. Sleek Rectangular Base Rim */}
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[5.8, 0.04, 2.4]} />
        <meshStandardMaterial
          color={isMeetingActive ? '#c084fc' : '#334155'}
          emissive={isMeetingActive ? '#c084fc' : '#1e293b'}
          emissiveIntensity={isMeetingActive ? 2.0 : 0.4}
        />
      </mesh>

      {/* 2. Twin Brushed Metallic Pedestals */}
      <mesh position={[-1.6, 0.36, 0]} castShadow>
        <boxGeometry args={[0.35, 0.68, 1.2]} />
        <meshStandardMaterial color="#0f172a" roughness={0.4} metalness={0.9} />
      </mesh>
      <mesh position={[1.6, 0.36, 0]} castShadow>
        <boxGeometry args={[0.35, 0.68, 1.2]} />
        <meshStandardMaterial color="#0f172a" roughness={0.4} metalness={0.9} />
      </mesh>

      {/* 3. Executive Charcoal Marble / Quartz Tabletop */}
      <mesh position={[0, 0.74, 0]} castShadow receiveShadow>
        <boxGeometry args={[5.2, 0.08, 2.0]} />
        <meshStandardMaterial color="#1e293b" roughness={0.3} metalness={0.5} />
      </mesh>

      {/* Edge Bevel Trim */}
      <mesh position={[0, 0.74, 0]}>
        <boxGeometry args={[5.24, 0.04, 2.04]} />
        <meshStandardMaterial
          color={isMeetingActive ? '#a855f7' : '#475569'}
          emissive={isMeetingActive ? '#a855f7' : '#334155'}
          emissiveIntensity={isMeetingActive ? 1.5 : 0.2}
        />
      </mesh>

      {/* Center Interactive Holographic Touchstrip */}
      <mesh position={[0, 0.785, 0]}>
        <boxGeometry args={[4.0, 0.01, 0.4]} />
        <meshStandardMaterial
          color="#00f0ff"
          emissive="#00f0ff"
          emissiveIntensity={isMeetingActive ? 2.2 : 0.8}
        />
      </mesh>

      {/* 10 Sleek Executive Conference Chairs for ALL 10 Agents:
          - 4 on North side facing South
          - 4 on South side facing North
          - 1 on West head facing East
          - 1 on East head facing West
      */}
      {/* North Side (facing South) */}
      {[-1.65, -0.55, 0.55, 1.65].map((x, i) => (
        <group key={`n-${i}`} position={[x, 0, -1.35]} rotation={[0, 0, 0]}>
          <mesh position={[0, 0.44, 0]} castShadow>
            <boxGeometry args={[0.48, 0.08, 0.44]} />
            <meshStandardMaterial color="#0f172a" roughness={0.4} />
          </mesh>
          <mesh position={[0, 0.80, -0.2]} rotation={[0.08, 0, 0]} castShadow>
            <boxGeometry args={[0.44, 0.65, 0.08]} />
            <meshStandardMaterial color="#090d16" roughness={0.4} />
          </mesh>
        </group>
      ))}

      {/* South Side (facing North) */}
      {[-1.65, -0.55, 0.55, 1.65].map((x, i) => (
        <group key={`s-${i}`} position={[x, 0, 1.35]} rotation={[0, Math.PI, 0]}>
          <mesh position={[0, 0.44, 0]} castShadow>
            <boxGeometry args={[0.48, 0.08, 0.44]} />
            <meshStandardMaterial color="#0f172a" roughness={0.4} />
          </mesh>
          <mesh position={[0, 0.80, -0.2]} rotation={[0.08, 0, 0]} castShadow>
            <boxGeometry args={[0.44, 0.65, 0.08]} />
            <meshStandardMaterial color="#090d16" roughness={0.4} />
          </mesh>
        </group>
      ))}

      {/* West Head (facing East - Conselho Chair) */}
      <group position={[-2.60, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
        <mesh position={[0, 0.44, 0]} castShadow>
          <boxGeometry args={[0.48, 0.08, 0.44]} />
          <meshStandardMaterial color="#0f172a" roughness={0.4} />
        </mesh>
        <mesh position={[0, 0.80, -0.2]} rotation={[0.08, 0, 0]} castShadow>
          <boxGeometry args={[0.44, 0.65, 0.08]} />
          <meshStandardMaterial color="#090d16" roughness={0.4} />
        </mesh>
      </group>

      {/* East Head (facing West - CRO Chair) */}
      <group position={[2.60, 0, 0]} rotation={[0, -Math.PI / 2, 0]}>
        <mesh position={[0, 0.44, 0]} castShadow>
          <boxGeometry args={[0.48, 0.08, 0.44]} />
          <meshStandardMaterial color="#0f172a" roughness={0.4} />
        </mesh>
        <mesh position={[0, 0.80, -0.2]} rotation={[0.08, 0, 0]} castShadow>
          <boxGeometry args={[0.44, 0.65, 0.08]} />
          <meshStandardMaterial color="#090d16" roughness={0.4} />
        </mesh>
      </group>
    </group>
  );
};

// -------------------------------------------------------------
// High-Tech Server Rack (Quant Lab & P&D)
// -------------------------------------------------------------
export const ServerRack: React.FC<{
  position: [number, number, number];
  rotation?: [number, number, number];
}> = ({ position, rotation = [0, 0, 0] }) => {
  const ledRef = useRef<THREE.MeshStandardMaterial>(null);

  useFrame(({ clock }) => {
    if (ledRef.current) {
      const pulse = Math.sin(clock.elapsedTime * 8) * 0.4 + 1.2;
      ledRef.current.emissiveIntensity = pulse;
    }
  });

  return (
    <group position={position} rotation={rotation}>
      {/* Cabinet Frame */}
      <mesh position={[0, 1.1, 0]} castShadow>
        <boxGeometry args={[0.85, 2.2, 0.75]} />
        <meshStandardMaterial color="#090d16" roughness={0.4} metalness={0.8} />
      </mesh>
      {/* Rack Inner Blades */}
      {[-0.6, -0.2, 0.2, 0.6].map((y, idx) => (
        <group key={idx} position={[0, 1.1 + y, 0.38]}>
          <mesh>
            <boxGeometry args={[0.74, 0.28, 0.02]} />
            <meshStandardMaterial color="#1e293b" metalness={0.9} />
          </mesh>
          {/* Green and Cyan Activity LEDs */}
          <mesh position={[-0.26, 0.06, 0.015]}>
            <boxGeometry args={[0.04, 0.04, 0.01]} />
            <meshStandardMaterial
              ref={idx === 0 ? ledRef : undefined}
              color="#10b981"
              emissive="#10b981"
              emissiveIntensity={1.5}
            />
          </mesh>
          <mesh position={[-0.18, 0.06, 0.015]}>
            <boxGeometry args={[0.04, 0.04, 0.01]} />
            <meshStandardMaterial color="#00f0ff" emissive="#00f0ff" emissiveIntensity={1.5} />
          </mesh>
          <mesh position={[-0.10, 0.06, 0.015]}>
            <boxGeometry args={[0.04, 0.04, 0.01]} />
            <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={1.2} />
          </mesh>
        </group>
      ))}
      {/* Top Status Light */}
      <mesh position={[0, 2.22, 0]}>
        <boxGeometry args={[0.80, 0.04, 0.70]} />
        <meshStandardMaterial color="#00f0ff" emissive="#00f0ff" emissiveIntensity={1.2} />
      </mesh>
    </group>
  );
};

// -------------------------------------------------------------
// Holographic News Globe / Antenna (News Desk Sector 2)
// -------------------------------------------------------------
export const HoloGlobe: React.FC<{
  position: [number, number, number];
}> = ({ position }) => {
  const globeRef = useRef<THREE.Mesh>(null);
  const ringRef = useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    if (globeRef.current) {
      globeRef.current.rotation.y = clock.elapsedTime * 0.8;
      globeRef.current.rotation.x = Math.sin(clock.elapsedTime * 0.5) * 0.2;
    }
    if (ringRef.current) {
      ringRef.current.rotation.z = -clock.elapsedTime * 1.2;
    }
  });

  return (
    <group position={position}>
      {/* Base Pedestal */}
      <mesh position={[0, 0.05, 0]}>
        <cylinderGeometry args={[0.10, 0.14, 0.10, 16]} />
        <meshStandardMaterial color="#0f172a" metalness={0.9} />
      </mesh>
      {/* Hologram Emitter Ring */}
      <mesh position={[0, 0.11, 0]}>
        <cylinderGeometry args={[0.08, 0.08, 0.02, 16]} />
        <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={2.5} />
      </mesh>
      {/* Floating Holographic Rotating Wireframe Globe */}
      <mesh ref={globeRef} position={[0, 0.36, 0]}>
        <icosahedronGeometry args={[0.18, 1]} />
        <meshStandardMaterial
          color="#f59e0b"
          emissive="#f59e0b"
          emissiveIntensity={1.8}
          wireframe
        />
      </mesh>
      {/* Rotating Orbital Ring */}
      <mesh ref={ringRef} position={[0, 0.36, 0]} rotation={[Math.PI / 4, 0, 0]}>
        <torusGeometry args={[0.26, 0.012, 8, 24]} />
        <meshStandardMaterial
          color="#00f0ff"
          emissive="#00f0ff"
          emissiveIntensity={2.0}
        />
      </mesh>
    </group>
  );
};

// -------------------------------------------------------------
// Ping-Pong Table (Break & Lounge Area)
// -------------------------------------------------------------
export const PingPongTable: React.FC<{
  position: [number, number, number];
  rotation?: [number, number, number];
}> = ({ position, rotation = [0, 0, 0] }) => {
  return (
    <group position={position} rotation={rotation}>
      {/* Metal Legs */}
      {[-1.0, 1.0].map((x) =>
        [-0.5, 0.5].map((z) => (
          <mesh key={`${x}-${z}`} position={[x, 0.35, z]} castShadow>
            <cylinderGeometry args={[0.03, 0.03, 0.70, 8]} />
            <meshStandardMaterial color="#1e293b" metalness={0.9} />
          </mesh>
        ))
      )}
      {/* Crossbar frame */}
      <mesh position={[0, 0.25, 0]}>
        <boxGeometry args={[2.1, 0.04, 1.0]} />
        <meshStandardMaterial color="#0f172a" metalness={0.8} />
      </mesh>
      {/* Tabletop Surface (Vibrant Navy Blue with White Edges) */}
      <mesh position={[0, 0.72, 0]} castShadow receiveShadow>
        <boxGeometry args={[2.5, 0.05, 1.4]} />
        <meshStandardMaterial color="#1e3a8a" roughness={0.3} />
      </mesh>
      {/* White Center Line */}
      <mesh position={[0, 0.748, 0]}>
        <boxGeometry args={[2.48, 0.005, 0.02]} />
        <meshStandardMaterial color="#ffffff" roughness={0.2} />
      </mesh>
      {/* Center Net */}
      <mesh position={[0, 0.82, 0]}>
        <boxGeometry args={[0.02, 0.15, 1.48]} />
        <meshStandardMaterial color="#f8fafc" roughness={0.5} />
      </mesh>
      {/* Rackets on table */}
      <mesh position={[-0.6, 0.76, 0.3]} rotation={[0, 0.4, 0]}>
        <cylinderGeometry args={[0.10, 0.10, 0.02, 16]} />
        <meshStandardMaterial color="#ef4444" roughness={0.6} />
      </mesh>
      <mesh position={[0.6, 0.76, -0.3]} rotation={[0, -0.6, 0]}>
        <cylinderGeometry args={[0.10, 0.10, 0.02, 16]} />
        <meshStandardMaterial color="#0284c7" roughness={0.6} />
      </mesh>
      {/* Ping-pong ball */}
      <mesh position={[0.4, 0.76, 0.1]}>
        <sphereGeometry args={[0.025, 12, 12]} />
        <meshStandardMaterial color="#f97316" roughness={0.2} />
      </mesh>
    </group>
  );
};

// -------------------------------------------------------------
// Lounge Modern Modular Sofa (Relaxation & Quarantine Area)
// -------------------------------------------------------------
export const LoungeSofa: React.FC<{
  position: [number, number, number];
  rotation?: [number, number, number];
  width?: number;
}> = ({ position, rotation = [0, 0, 0], width = 2.2 }) => {
  return (
    <group position={position} rotation={rotation}>
      {/* Base Platform / Wooden / Dark metal feet */}
      <mesh position={[0, 0.08, 0]} castShadow>
        <boxGeometry args={[width, 0.16, 0.9]} />
        <meshStandardMaterial color="#0b0f19" roughness={0.6} metalness={0.4} />
      </mesh>
      {/* Main Seat Cushion */}
      <mesh position={[0, 0.32, 0.05]} castShadow receiveShadow>
        <boxGeometry args={[width - 0.05, 0.32, 0.78]} />
        <meshStandardMaterial color="#1e293b" roughness={0.8} />
      </mesh>
      {/* Backrest */}
      <mesh position={[0, 0.65, -0.32]} castShadow>
        <boxGeometry args={[width, 0.55, 0.22]} />
        <meshStandardMaterial color="#334155" roughness={0.8} />
      </mesh>
      {/* Accent Lumbar Neon Stripe */}
      <mesh position={[0, 0.42, -0.20]}>
        <boxGeometry args={[width - 0.2, 0.03, 0.02]} />
        <meshStandardMaterial color="#38bdf8" emissive="#38bdf8" emissiveIntensity={0.8} />
      </mesh>
    </group>
  );
};

