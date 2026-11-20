import { AgentStatus } from '@/types';

/** Alas do escritório por ativo (sector gravado pelo sync: 1 GOLD, 2 US500Cash, 3 BTCUSD). */
export interface Zone {
  key: 'GOLD' | 'US500' | 'BTC';
  sector: number;
  label: string;
  sub: string;
  color: string;
  origin: [number, number]; // canto da primeira mesa (x, z)
  cols: number;
}

export const ZONES: Zone[] = [
  { key: 'GOLD', sector: 1, label: 'GOLD', sub: 'XAU · ouro', color: '#f5b83d', origin: [-14.2, -4.2], cols: 3 },
  { key: 'US500', sector: 2, label: 'US500', sub: 'S&P 500 · índice', color: '#7c8cff', origin: [-14.2, 2.6], cols: 3 },
  { key: 'BTC', sector: 3, label: 'BTCUSD', sub: 'bitcoin · orderflow', color: '#ff8a3d', origin: [-3.4, -4.2], cols: 6 },
];

export const DESK_DX = 3.1;
export const DESK_DZ = 3.4;

export const GROUP_STYLE: Record<string, { label: string; shirt: string; badge: string }> = {
  antigo: { label: 'Antigo', shirt: '#94a3b8', badge: 'bg-slate-500/25 text-slate-200 ring-slate-400/40' },
  v4: { label: 'Novo · v4', shirt: '#22d3ee', badge: 'bg-cyan-500/20 text-cyan-200 ring-cyan-400/40' },
  of_btc: { label: 'Novo · orderflow', shirt: '#a78bfa', badge: 'bg-violet-500/20 text-violet-200 ring-violet-400/40' },
};

export function groupOf(agentId: string): 'antigo' | 'v4' | 'of_btc' {
  if (agentId.startsWith('of_btc_')) return 'of_btc';
  if (agentId.startsWith('v4_')) return 'v4';
  return 'antigo';
}

/** Nome curto para a plaquinha. */
export function shortName(agentId: string): string {
  if (agentId.startsWith('of_btc_')) {
    const [, , num, fam, ...rest] = agentId.split('_');
    return `OF·${num} ${fam.toUpperCase()} ${rest.join(' ')}`;
  }
  if (agentId.startsWith('v4_')) {
    const parts = agentId.replace(/^v4_/, '').split('_');
    return `V4 · ${parts.map((p) => p.toUpperCase()).join(' ')}`;
  }
  return agentId.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface Seat {
  agent: AgentStatus;
  zone: Zone;
  pos: [number, number, number];
}

/** Posição de cada agente ativo: ordem estável (antigos, v4, orderflow; depois nome). */
export function seatAgents(agents: AgentStatus[]): Seat[] {
  const order = { antigo: 0, v4: 1, of_btc: 2 } as const;
  const seats: Seat[] = [];
  for (const zone of ZONES) {
    const mine = agents
      .filter((a) => Number(a.sector) === zone.sector)
      .sort((a, b) => order[groupOf(a.agent_id)] - order[groupOf(b.agent_id)] || a.agent_id.localeCompare(b.agent_id));
    mine.forEach((agent, i) => {
      const col = i % zone.cols;
      const row = Math.floor(i / zone.cols);
      seats.push({ agent, zone, pos: [zone.origin[0] + col * DESK_DX, 0, zone.origin[1] + row * DESK_DZ] });
    });
  }
  return seats;
}

/** Retângulo do tapete de uma ala (cobre as mesas ocupadas). */
export function zoneRect(zone: Zone, count: number): { cx: number; cz: number; w: number; d: number } {
  const cols = Math.min(zone.cols, Math.max(count, 1));
  const rows = Math.max(1, Math.ceil(count / zone.cols));
  const w = (cols - 1) * DESK_DX + 2.9;
  const d = (rows - 1) * DESK_DZ + 3.1;
  return { cx: zone.origin[0] + ((cols - 1) * DESK_DX) / 2, cz: zone.origin[1] + ((rows - 1) * DESK_DZ) / 2 - 0.25, w, d };
}

export function fmtUsd(v: number | null | undefined, sign = true): string {
  const n = Math.round((Number(v) || 0) * 100) / 100;
  const s = sign && n > 0 ? '+' : n < 0 ? '-' : '';
  return `${s}$${Math.abs(n).toFixed(2)}`;
}
