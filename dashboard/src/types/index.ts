export type AgentState = 'IDLE' | 'ANALYZING' | 'EXECUTING' | 'QUARANTINED' | 'IN_MEETING';

export interface AgentStatus {
  agent_id: string;
  name: string;
  sector: number;
  strategy_style?: string | null;
  current_state: AgentState | string;
  last_thought: string;
  allocation_weight: number;
  updated_at?: string;
  total_profit?: number;
  total_pnl?: number;
  pnl?: number;
  consecutive_losses?: number;
  quarantine_until?: string | null;
}

export interface AgentLearning {
  id: number;
  agent_id: string;
  symbol: string;
  cycle_loss: number;
  technical_failure: string;
  vaccine_rule: Record<string, any>;
  created_at: string;
}

export interface MarketContext {
  id?: number;
  crypto_sentiment: number; // -10 to +10
  gold_sentiment: number;   // -10 to +10
  red_flag_pause_trading: boolean;
  key_driver: string;
  created_at?: string;
}

export interface MT5AccountStatus {
  id: number;
  balance: number;
  equity: number;
  floating_pnl: number;
  free_margin: number;
  margin_level: number;
  total_tp_gain: number;
  total_sl_loss: number;
  win_count: number;
  loss_count: number;
  is_connected: boolean;
  updated_at?: string;
}

export interface SystemConfig {
  id: number;
  trading_mode: 'DEMO' | 'REAL' | string;
  active_assets?: string[];
  updated_at?: string;
}

export interface Trade {
  ticket_mt5: number;
  agent_id: string;
  symbol: string;
  order_type: 'BUY' | 'SELL' | string;
  volume: number;
  entry_price: number;
  current_price?: number | null;
  sl: number;
  tp: number;
  close_price?: number | null;
  profit_usd: number;
  status: 'OPEN' | 'CLOSED' | string;
  exit_reason?: 'TP_HIT' | 'SL_HIT' | 'OPEN' | string | null;
  technical_rationale?: string | null;
  risk_amount?: number;
  confidence?: number;
  dry_run?: boolean;
  opened_at: string;
  closed_at?: string | null;
  execution_account?: 'DEMO' | 'REAL' | string | null;
}

export interface CumulativeEquityPoint {
  time: string;
  timestamp: number;
  total: number;
  ops_alpha?: number;
  ops_delta?: number;
  ops_beta?: number;
  ops_epsilon?: number;
  ops_gamma?: number;
  [key: string]: string | number | undefined;
}

export interface AgentPerformanceItem {
  agentId: string;
  pnl: number;
  formattedPnL: string;
  isPositive: boolean;
  wins: number;
  losses: number;
  totalTrades: number;
  closedTrades: number;
  openTrades: number;
  winRate: number;
  colorClass: string;
  dotColorClass: string;
}

export type AgentPerformanceMap = Record<string, AgentPerformanceItem>;
