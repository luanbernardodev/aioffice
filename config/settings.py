"""Configurações globais carregadas do ambiente (.env)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# --- Serviços externos ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Necessário apenas se a chave não estiver vinculada a um workspace (ex.: wrkspc_...)
ANTHROPIC_WORKSPACE_ID = os.getenv("ANTHROPIC_WORKSPACE_ID", "")

# --- Servidor MCP MetaTrader 5 (Setor 3 Auditoria - Exclusivo Read-Only) ---
MT5_MCP_ADDRESS = os.getenv("MT5_MCP_ADDRESS", "http://127.0.0.1:22346/mcp")
MT5_MCP_API_KEY = os.getenv("MT5_MCP_API_KEY", "t8q5x0V6N7XrY/9/kGVb/kaOPWH4fV/ui+beHGxfjM")

# --- MetaTrader 5 (DEMO & REAL) ---
MT5_LOGIN_DEMO = _int("MT5_LOGIN_DEMO", _int("MT5_LOGIN", 309673774))
MT5_PASSWORD_DEMO = os.getenv("MT5_PASSWORD_DEMO", os.getenv("MT5_PASSWORD", ""))
MT5_SERVER_DEMO = os.getenv("MT5_SERVER_DEMO", os.getenv("MT5_SERVER", "XMGlobal-MT5 6"))

MT5_LOGIN_REAL = _int("MT5_LOGIN_REAL", 410574578)
MT5_PASSWORD_REAL = os.getenv("MT5_PASSWORD_REAL", "")
MT5_SERVER_REAL = os.getenv("MT5_SERVER_REAL", "XMGlobal-MT5 16")

# Fallback para conexões padrão
MT5_LOGIN = _int("MT5_LOGIN", MT5_LOGIN_DEMO)
MT5_PASSWORD = os.getenv("MT5_PASSWORD", MT5_PASSWORD_DEMO)
MT5_SERVER = os.getenv("MT5_SERVER", MT5_SERVER_DEMO)
DRY_RUN = _bool("DRY_RUN", True)
VERBOSE_LOGS = _bool("VERBOSE_LOGS", True)

# --- Trading ---
SYMBOLS = ["BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD"]
TIMEFRAME = "M15"
RISK_PER_TRADE = 0.01  # 1% do saldo por operação
MOCK_BALANCE = 10_000.0  # saldo usado no modo simulação
MAGIC_NUMBER = 20260101

# --- Modelos ---
MODEL_FAST = os.getenv("MODEL_FAST", "claude-haiku-5-5")   # Setores 1 e 2
MODEL_SMART = os.getenv("MODEL_SMART", "claude-sonnet-5-5")  # Setores 3, 4, 5 e 6

# --- Agentes: id -> (setor, nome exibido no escritório 2D) ---
AGENTS = {
    "ops_alpha": (1, "Ops Alpha — Trend Following M15"),
    "ops_beta": (1, "Ops Beta — Mean Reversion Sniper M15"),
    "ops_gamma": (1, "Ops Gamma — Volatility Breakout M15"),
    "ops_delta": (1, "Ops Delta — SMC/Liquidity Sweep Scalper M1/M5"),
    "ops_epsilon": (1, "Ops Epsilon — VWAP + Momentum Scalper M1/M5"),
    "news_desk": (2, "News Desk"),
    "analytics": (3, "Analytics"),
    "rnd": (4, "P&D Quant"),
    "manager": (5, "Gerente de Risco"),
    "boardroom": (6, "Sala de Reunião"),
}
# Agentes-base do Setor 1 (clones criados em runtime, ex.: ops_beta_v2, vivem apenas no banco;
# use DatabaseManager.get_ops_agent_ids() para a lista dinâmica sem demitidos).
OPS_AGENT_IDS = [a for a, (sector, _) in AGENTS.items() if sector == 1]

# --- Estratégia (chave = estratégia-base) -> timeframe do Sentinela ---
STRATEGY_TIMEFRAMES = {
    "ops_alpha": "M15", "ops_beta": "M15", "ops_gamma": "M15",
    "ops_delta": "M5", "ops_epsilon": "M5",
}
# Timeframe usado para liquidar SL/TP simulados (scalpers precisam de granularidade fina)
STRATEGY_SETTLE_TIMEFRAMES = {"ops_delta": "M1", "ops_epsilon": "M1"}

# --- Parâmetros iniciais de estratégia dos agentes operacionais ---
DEFAULT_STRATEGY_PARAMS = {
    "ops_alpha": {"min_confidence": 60, "sl_atr_multiplier": 1.5, "tp_atr_multiplier": 3.0},
    "ops_beta": {"min_confidence": 65, "sl_atr_multiplier": 1.2, "tp_atr_multiplier": 2.4},
    "ops_gamma": {"min_confidence": 65, "sl_atr_multiplier": 1.0, "tp_atr_multiplier": 3.0},
    # Scalpers: stop curto, alvo rápido
    "ops_delta": {"min_confidence": 65, "sl_atr_multiplier": 0.8, "tp_atr_multiplier": 1.6},
    "ops_epsilon": {"min_confidence": 62, "sl_atr_multiplier": 0.7, "tp_atr_multiplier": 1.4},
}

# --- Gerenciamento de risco (Setor 5) ---
QUARANTINE_MINUTES = 60      # 1ª perda consecutiva
LOSSES_CALIBRATE = 2         # evento para o Setor 3 (ajuste correlacionado)
LOSSES_MEETING = 3           # reunião geral + calibração extrema
LOSSES_FIRE = 4              # demissão + clonagem do melhor agente
CLONE_MUTATION_PCT = 0.07    # mutação máxima (±7%) dos parâmetros do clone

# --- Notícias / gate macro (Setor 3) ---
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")          # Finnhub API Key gratuita
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")  # token gratuito (opcional)
NEWS_WINDOW_HOURS = 4
MACRO_VALIDITY_MIN = 45      # validade padrão do "OK macro" do Setor 3 (> NEWS_INTERVAL_MIN)

# --- Agendamento (segundos / minutos / hora) ---
SENTINEL_INTERVAL_SEC = 60
NEWS_INTERVAL_MIN = 30
DAILY_RUN_TIME = "00:05"
