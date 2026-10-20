import { Trade } from '@/types';

export interface AgentMetrics {
  agentId: string;
  netPnL: number;
  formattedPnL: string;
  isPositive: boolean;
  totalTrades: number;
  closedTradesCount: number;
  winCount: number;
  lossCount: number;
  winRate: number;
  grossWins: number;
  grossLosses: number;
  profitFactor: number;
  colorClass: string;
  dotColorClass: string;
}

/**
 * Calcula o Net PnL (Lucro Líquido Acumulado) de um ou todos os agentes.
 * Lê a lista de trades, filtra rigorosamente status === 'CLOSED'
 * e soma os valores da coluna profit_usd agrupados por agent_id.
 */
export function calculateNetPnLByAgent(trades: Trade[]): Record<string, number> {
  const pnlMap: Record<string, number> = {};

  if (!trades || !Array.isArray(trades)) {
    return pnlMap;
  }

  for (const trade of trades) {
    const status = String(trade.status || '').trim().toUpperCase();
    if (status === 'CLOSED' && trade.agent_id) {
      const profit = Number(trade.profit_usd);
      if (!isNaN(profit)) {
        pnlMap[trade.agent_id] = (pnlMap[trade.agent_id] || 0) + profit;
      }
    }
  }

  // Arredonda para 2 casas decimais para evitar imprecisões de float
  for (const agentId of Object.keys(pnlMap)) {
    pnlMap[agentId] = Math.round(pnlMap[agentId] * 100) / 100;
  }

  return pnlMap;
}

/**
 * Retorna o Net PnL de um agente específico
 */
export function getAgentNetPnL(trades: Trade[], agentId: string): number {
  if (!trades || !agentId) return 0;
  let total = 0;
  for (const trade of trades) {
    const status = String(trade.status || '').trim().toUpperCase();
    if (status === 'CLOSED' && trade.agent_id === agentId) {
      const profit = Number(trade.profit_usd);
      if (!isNaN(profit)) {
        total += profit;
      }
    }
  }
  return Math.round(total * 100) / 100;
}

/**
 * Formata um valor de PnL para exibição no padrão das tags 3D e painéis:
 * Exemplo: +$30.00 ou -$20.00
 */
export function formatPnL(value: number): {
  formatted: string;
  isPositive: boolean;
  colorClass: string;
  dotColorClass: string;
} {
  const isPositive = value > 0;
  const isNegative = value < 0;
  const sign = isPositive ? '+' : isNegative ? '-' : '';
  const absVal = Math.abs(value).toFixed(2);
  const formatted = `${sign}$${absVal}`;

  return {
    formatted,
    isPositive,
    colorClass: isPositive ? 'text-emerald-400' : isNegative ? 'text-rose-400' : 'text-cyan-400',
    dotColorClass: isPositive ? 'bg-emerald-400' : isNegative ? 'bg-rose-500' : 'bg-cyan-400',
  };
}

/**
 * Extrai métricas completas e consistentes de um agente para cards 2D e tabelas
 */
export function getAgentPerformanceMetrics(trades: Trade[], agentId: string): AgentMetrics {
  const agentTrades = (trades || []).filter((t) => t.agent_id === agentId);
  const closedTrades = agentTrades.filter((t) => String(t.status || '').trim().toUpperCase() === 'CLOSED');

  let netPnL = 0;
  let grossWins = 0;
  let grossLosses = 0;
  let winCount = 0;
  let lossCount = 0;

  for (const t of closedTrades) {
    const pnl = Number(t.profit_usd) || 0;
    netPnL += pnl;
    if (pnl > 0) {
      grossWins += pnl;
      winCount++;
    } else if (pnl < 0) {
      grossLosses += Math.abs(pnl);
      lossCount++;
    }
  }

  netPnL = Math.round(netPnL * 100) / 100;
  grossWins = Math.round(grossWins * 100) / 100;
  grossLosses = Math.round(grossLosses * 100) / 100;

  const totalDecidedTrades = winCount + lossCount;
  const winRate = totalDecidedTrades > 0 ? Math.round((winCount / totalDecidedTrades) * 1000) / 10 : 0;
  const profitFactor = grossLosses > 0
    ? Math.round((grossWins / grossLosses) * 100) / 100
    : grossWins > 0
    ? 99.9
    : 1.0;

  const fmt = formatPnL(netPnL);

  return {
    agentId,
    netPnL,
    formattedPnL: fmt.formatted,
    isPositive: fmt.isPositive,
    totalTrades: agentTrades.length,
    closedTradesCount: closedTrades.length,
    winCount,
    lossCount,
    winRate,
    grossWins,
    grossLosses,
    profitFactor,
    colorClass: fmt.colorClass,
    dotColorClass: fmt.dotColorClass,
  };
}
