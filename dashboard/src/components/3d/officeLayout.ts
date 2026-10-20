/**
 * Layout, slots de quarentena anti-overlap e gerador de rotas ortogonais
 * com hub no Corredor Central (x: 0, z: 0) desviando de todas as mesas.
 */

export interface QuarantineSlot {
  pos: [number, number, number];
  facingRot: number;
  label: string;
}

/**
 * 2. SLOTS DE QUARENTENA DINÂMICOS (ANTI-OVERLAP)
 * - ops_alpha e ops_beta -> Lados opostos da mesa de ping-pong.
 * - ops_gamma -> Perto do bebedouro.
 * - ops_delta e ops_epsilon -> Sofá / Áreas de canto.
 */
export const QUARANTINE_SLOTS: Record<string, QuarantineSlot> = {
  ops_alpha: {
    pos: [10.5, 0, 12.6], // Lado Norte da mesa de ping-pong (olhando para a mesa em Z+)
    facingRot: 0,
    label: 'Ping-Pong Norte',
  },
  ops_beta: {
    pos: [10.5, 0, 16.2], // Lado Sul da mesa de ping-pong (olhando para a mesa em Z-)
    facingRot: Math.PI,
    label: 'Ping-Pong Sul',
  },
  ops_gamma: {
    pos: [17.4, 0, 12.8], // Perto do bebedouro (em 18.4, 12.8)
    facingRot: Math.PI / 2,
    label: 'Bebedouro',
  },
  ops_delta: {
    pos: [18.2, 0, 15.8], // Sofá Canto Leste do Lounge
    facingRot: -Math.PI / 2,
    label: 'Sofá Canto Leste',
  },
  ops_epsilon: {
    pos: [13.8, 0, 16.5], // Sofá Canto Sul do Lounge
    facingRot: Math.PI,
    label: 'Sofá Canto Sul',
  },
  // Demais agentes (caso convocados para descompressão)
  news_macro: {
    pos: [15.2, 0, 12.6], // Mesa de bilhar lado norte
    facingRot: 0,
    label: 'Bilhar Norte',
  },
  auditor_quant: {
    pos: [15.2, 0, 16.2], // Mesa de bilhar lado sul
    facingRot: Math.PI,
    label: 'Bilhar Sul',
  },
  rnd_engineer: {
    pos: [12.8, 0, 12.6],
    facingRot: 0,
    label: 'Lounge Hall',
  },
  cro_manager: {
    pos: [12.8, 0, 16.2],
    facingRot: Math.PI,
    label: 'Lounge Lateral',
  },
  boardroom_chair: {
    pos: [16.8, 0, 14.4],
    facingRot: -Math.PI / 2,
    label: 'Lounge Poltrona',
  },
};

export function getQuarantineSlot(agentId: string): QuarantineSlot {
  return QUARANTINE_SLOTS[agentId] || {
    pos: [14.0, 0, 14.4],
    facingRot: 0,
    label: 'Lounge Genérico',
  };
}

/**
 * 3. PATHFINDING ORTOGONAL: ROTAS EM "L" COM HUB EM [0, 0]
 * Garante que nenhuma rota passe pelo centro da Sala 6 (mesa de reunião) ou mesas de jogos.
 * 
 * Regra:
 * 1. Origem -> Sai para o corredor da sala (X = -6.0 a oeste, X = +6.0 a leste, ou Z = -3.0 para CRO).
 * 2. Alinha em Z = 0.0.
 * 3. Anda até o Corredor Central em [0.0, 0.0].
 * 4. A partir de [0.0, 0.0], caminha em ângulos de 90° até o destino.
 */
export function buildOrthogonalPathToMeeting(
  startPos: [number, number, number],
  chairPos: [number, number, number],
  doorWaypoints: [number, number][] = []
): [number, number][] {
  const path: [number, number][] = [];
  const [sx, , sz] = startPos;
  const [cx, , cz] = chairPos;

  // Se já está na cadeira (distância mínima)
  if (Math.hypot(sx - cx, sz - cz) < 0.3) {
    return [[cx, cz]];
  }

  // 1. Saída da sala até o corredor lateral
  if (doorWaypoints && doorWaypoints.length > 0) {
    doorWaypoints.forEach((wp) => path.push([wp[0], wp[1]]));
  } else if (sx < -6.0) {
    path.push([-6.0, sz]);
  } else if (sx > 6.0) {
    path.push([6.0, sz]);
  } else if (sz < -3.0) {
    path.push([0.0, -3.0]);
  }

  // 2. Alinhamento com o Corredor Central Leste-Oeste (Z = 0.0)
  const lastX = path.length > 0 ? path[path.length - 1][0] : sx;
  path.push([lastX, 0.0]);

  // 3. Corredor Central (Hub [0, 0])
  path.push([0.0, 0.0]);

  // 4. Do Hub [0, 0] até a cadeira da Reunião (Setor 6, Z = 3.5):
  const isNorthChair = cz < 3.0; // Z = 2.15
  const isEastHead = cx > 2.0;    // X = 2.60, Z = 3.50
  const isWestHead = cx < -2.0;   // X = -2.60, Z = 3.50

  if (isWestHead) {
    // Cabeceira Oeste: desvia pela esquerda do corredor
    path.push([-3.4, 0.0]);
    path.push([-3.4, 3.50]);
    path.push([cx, cz]);
  } else if (isEastHead) {
    // Cabeceira Leste: desvia pela direita do corredor
    path.push([3.4, 0.0]);
    path.push([3.4, 3.50]);
    path.push([cx, cz]);
  } else if (isNorthChair) {
    // Cadeiras do Norte: acessa de frente sem atravessar a mesa
    path.push([cx, 0.0]);
    path.push([cx, 0.8]);
    path.push([cx, cz]);
  } else {
    // Cadeiras do Sul (Z = 4.85): contorna a mesa pelas laterais seguras X = -3.4 ou +3.4
    const bypassX = cx >= 0 ? 3.4 : -3.4;
    path.push([bypassX, 0.0]);
    path.push([bypassX, 4.85]);
    path.push([cx, cz]);
  }

  return cleanRedundantWaypoints(path);
}

/**
 * Rota ortogonal da mesa até o slot de quarentena via Corredor Central [0, 0]
 */
export function buildOrthogonalPathToQuarantine(
  startPos: [number, number, number],
  quarantinePos: [number, number, number],
  doorWaypoints: [number, number][] = []
): [number, number][] {
  const path: [number, number][] = [];
  const [sx, , sz] = startPos;
  const [qx, , qz] = quarantinePos;

  // 1. Saída da mesa
  if (doorWaypoints && doorWaypoints.length > 0) {
    doorWaypoints.forEach((wp) => path.push([wp[0], wp[1]]));
  } else if (sx < -6.0) {
    path.push([-6.0, sz]);
  } else if (sx > 6.0) {
    path.push([6.0, sz]);
  } else if (sz < -3.0) {
    path.push([0.0, -3.0]);
  }

  // 2. Alinhamento com Z = 0.0
  const lastX = path.length > 0 ? path[path.length - 1][0] : sx;
  path.push([lastX, 0.0]);

  // 3. Ponto de controle: Corredor Central
  path.push([0.0, 0.0]);

  // 4. Do Corredor Central até o Lounge: desce pelo corredor central até Z = 8.0
  path.push([0.0, 8.0]);

  // 5. Vira em direção ao Lounge (Leste)
  path.push([7.0, 8.0]);

  // 6. Desce pelo corredor de acesso do Lounge (Sul)
  path.push([7.0, 11.5]);

  // 7. Acesso ao slot exclusivo sem colidir com as mesas de jogos
  // Se for ping-pong sul (X=10.5, Z=16.2), contorna pelo corredor oeste da mesa
  if (qx === 10.5 && qz > 14.5) {
    path.push([8.8, 11.5]);
    path.push([8.8, qz]);
    path.push([qx, qz]);
  } else {
    path.push([qx, 11.5]);
    path.push([qx, qz]);
  }

  return cleanRedundantWaypoints(path);
}

/**
 * Rota ortogonal de retorno para a mesa de trabalho (IDLE) a partir de qualquer ponto
 */
export function buildOrthogonalPathToDesk(
  currentPos: [number, number, number],
  deskPos: [number, number, number],
  doorWaypoints: [number, number][] = []
): [number, number][] {
  const path: [number, number][] = [];
  const [cx, , cz] = currentPos;
  const [dx, , dz] = deskPos;

  // Se já está na mesa, não gera rota
  if (Math.hypot(cx - dx, cz - dz) < 0.3) {
    return [[dx, dz]];
  }

  // Se está na área do Lounge (Z > 10.0, X > 6.0), sai pelo corredor do lounge
  if (cz > 10.0 && cx > 6.0) {
    path.push([cx, 11.5]);
    path.push([7.0, 11.5]);
    path.push([7.0, 8.0]);
    path.push([0.0, 8.0]);
  }
  // Se está na Sala de Reunião (Z entre 1.5 e 5.5, X entre -4.0 e +4.0), sai pelas laterais ou norte
  else if (cz > 1.0 && cz < 5.5 && Math.abs(cx) < 4.0) {
    const exitBypassX = cx >= 0 ? 3.4 : -3.4;
    path.push([exitBypassX, cz]);
    path.push([exitBypassX, 0.0]);
  }

  // Passa pelo Corredor Central [0, 0]
  path.push([0.0, 0.0]);

  // Do Corredor Central [0, 0] para a sala da mesa:
  if (dx < -6.0) {
    // Setor 1: Operadores
    path.push([-6.0, 0.0]);
    path.push([-6.0, dz]);
    path.push([dx, dz]);
  } else if (dx > 6.0) {
    // Setores 2, 3, 4: Oráculo, Auditor, P&D
    path.push([6.0, 0.0]);
    path.push([6.0, dz]);
    path.push([dx, dz]);
  } else {
    // Setor 5: CRO
    path.push([0.0, -3.0]);
    path.push([dx, dz]);
  }

  return cleanRedundantWaypoints(path);
}

/**
 * Rota ortogonal entre salas (ex: Oráculo S2 -> Operadores S1, Auditor S3 -> S1, Auditor S3 -> P&D S4)
 */
export function buildOrthogonalInterSectorPath(
  startPos: [number, number, number],
  destPos: [number, number, number]
): [number, number][] {
  const path: [number, number][] = [];
  const [sx, , sz] = startPos;
  const [dx, , dz] = destPos;

  // 1. Saída da sala até o corredor
  const outX = sx < 0 ? -6.0 : 6.0;
  path.push([outX, sz]);
  path.push([outX, 0.0]);

  // 2. Passa pelo Corredor Central [0, 0]
  path.push([0.0, 0.0]);

  // 3. Entra no corredor da sala de destino
  const inX = dx < 0 ? -6.0 : 6.0;
  path.push([inX, 0.0]);
  path.push([inX, dz]);
  path.push([dx, dz]);

  return cleanRedundantWaypoints(path);
}

/**
 * Remove waypoints duplicados consecutivos ou colineares desnecessários
 */
function cleanRedundantWaypoints(waypoints: [number, number][]): [number, number][] {
  if (waypoints.length <= 1) return waypoints;

  const result: [number, number][] = [waypoints[0]];

  for (let i = 1; i < waypoints.length; i++) {
    const prev = result[result.length - 1];
    const curr = waypoints[i];
    // Se a distância for praticamente zero, pula
    if (Math.hypot(curr[0] - prev[0], curr[1] - prev[1]) > 0.05) {
      result.push(curr);
    }
  }

  return result;
}
