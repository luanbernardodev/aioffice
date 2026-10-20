"""Ponte com o MetaTrader 5 com modo Mock (candles sintéticos) para qualquer SO."""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from config import settings

log = logging.getLogger("mt5")

try:  # MetaTrader5 só existe no Windows
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # noqa: BLE001
    mt5 = None

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}

# Parâmetros do mercado simulado: preço base, volatilidade por candle, tamanho do contrato
MOCK_SPECS = {
    "BTCUSD": {"base": 65000.0, "vol": 0.0022, "contract": 1.0, "amp": 1.0, "seed": 11.0},
    "ETHUSD": {"base": 3200.0, "vol": 0.0026, "contract": 1.0, "amp": 1.1, "seed": 23.0},
    "SOLUSD": {"base": 150.0, "vol": 0.0034, "contract": 1.0, "amp": 1.3, "seed": 37.0},
    "XAUUSD": {"base": 2400.0, "vol": 0.0007, "contract": 100.0, "amp": 0.4, "seed": 51.0},
}
DEFAULT_SPEC = {"base": 100.0, "vol": 0.002, "contract": 1.0, "amp": 1.0, "seed": 7.0}


def _pseudo_rand(idx: np.ndarray, salt: float) -> np.ndarray:
    """Ruído determinístico em [-1, 1] por índice de candle (consistente entre chamadas)."""
    x = np.sin(idx * 12.9898 + salt * 78.233) * 43758.5453
    return (x - np.floor(x)) * 2.0 - 1.0


# Códigos de retorno de execução do MetaTrader 5 e suas interpretações
MT5_RETCODES: Dict[int, str] = {
    10004: "Requote (10004) - Preço mudou durante a requisição",
    10006: "Request rejected (10006) - Requisição rejeitada pela corretora",
    10007: "Request canceled by trader (10007) - Cancelado pelo trader",
    10008: "Order placed (10008) - Ordem colocada com sucesso",
    10009: "Request executed successfully (10009 / TRADE_RETCODE_DONE)",
    10010: "Request executed partially (10010) - Executado parcialmente",
    10011: "Request processing error (10011) - Erro de processamento",
    10012: "Request timed out (10012) - Timeout na execução",
    10013: "Invalid request / Invalid stops (10013) - Parâmetros de SL/TP ou requisição inválidos",
    10014: "Invalid volume (10014) - Volume de lote inválido",
    10015: "Invalid price (10015) - Preço de entrada inválido",
    10016: "Invalid stops (10016) - Níveis de SL ou TP muito próximos ou inválidos",
    10017: "Trade disabled (10017) - Negociação desabilitada na conta ou símbolo",
    10018: "Market closed (10018) - Mercado fechado",
    10019: "No money / Insufficient margin (10019) - Margem insuficiente para abrir a ordem",
    10020: "Price changed (10020) - Preço oscilou",
    10021: "Off quotes (10021) - Sem cotação disponível no momento",
    10022: "Order state changed (10022) - Estado da ordem mudou",
    10023: "Too many open requests (10023) - Fila de requisições cheia",
    10024: "No changes (10024) - Nenhuma alteração",
    10025: "AutoTrading disabled by server (10025) - AutoTrading bloqueado pelo servidor",
    10026: "AutoTrading disabled by client terminal (10026) - Habilite o botão 'Algo Trading' no MT5",
    10027: "AutoTrading disabled (10027) - Negociação automatizada desabilitada",
    10028: "Request locked for processing (10028)",
    10029: "Order or position frozen (10029)",
    10030: "Unsupported filling mode (10030) - Tipo de preenchimento não suportado pela corretora",
    10031: "Connection with trade server lost (10031) - Conexão perdida com servidor",
    10032: "Operation allowed only for live accounts (10032)",
    10033: "Maximum orders reached (10033) - Limite máximo de ordens atingido",
    10034: "Maximum volume reached (10034) - Limite máximo de volume atingido",
    10035: "Invalid order type (10035)",
    10036: "Position already closed (10036) - Posição já se encontra fechada",
    10038: "Close volume exceeds position volume (10038)",
    10039: "Close order already exists (10039)",
    10040: "Position limit reached (10040)",
}


def describe_retcode(code: Optional[int]) -> str:
    """Traduz o retcode numérico do MT5 para mensagem clara em português."""
    if code is None:
        return "Sem código retornado"
    return MT5_RETCODES.get(code, f"Código MT5 não mapeado ({code})")


def resolve_symbol(symbol: str) -> str:
    """Resolve aliases de símbolos da corretora XM (ex.: XAUUSD <-> GOLD)."""
    if mt5 is None:
        return symbol
    try:
        if mt5.symbol_info(symbol) is not None:
            return symbol
        if symbol == "XAUUSD" and mt5.symbol_info("GOLD") is not None:
            return "GOLD"
        if symbol == "GOLD" and mt5.symbol_info("XAUUSD") is not None:
            return "XAUUSD"
    except Exception:
        pass
    return symbol


class MT5Bridge:

    def __init__(self) -> None:
        self.mock = True
        self.connected = False
        self.demo_login = settings.MT5_LOGIN_DEMO
        self.demo_password = settings.MT5_PASSWORD_DEMO
        self.demo_server = settings.MT5_SERVER_DEMO
        self.real_login = settings.MT5_LOGIN_REAL
        self.real_password = settings.MT5_PASSWORD_REAL
        self.real_server = settings.MT5_SERVER_REAL
        self.ensure_connection()

    def login_account(self, login: int, password: str, server: str, timeout: int = 15000) -> bool:
        """Alterna a conta ativa do MT5 dinamicamente com tratamento seguro de erro e reconnect."""
        if self.mock or mt5 is None or not login:
            return True
        try:
            curr_acc = mt5.account_info()
            if curr_acc and getattr(curr_acc, "login", None) == login:
                return True
            if mt5.login(login=login, password=password, server=server, timeout=timeout):
                log.info("[MT5 CONTEXT SWITCH] Logado com sucesso na conta #%s (%s)", login, server)
                return True
            log.warning("[MT5 CONTEXT SWITCH] mt5.login falhou para #%s. Tentando mt5.initialize...", login)
            if mt5.initialize(login=login, password=password, server=server, timeout=timeout):
                self.mock = False
                self.connected = True
                log.info("[MT5 CONTEXT SWITCH] Reinicializado com sucesso na conta #%s (%s)", login, server)
                return True
            err = mt5.last_error()
            log.error("[MT5 CONTEXT SWITCH] Falha ao alternar para conta #%s: %s", login, err)
            return False
        except Exception as exc:
            log.error("[MT5 CONTEXT SWITCH] Erro ao alternar conta MT5 para #%s: %s", login, exc)
            return False

    def ensure_connection(self) -> bool:
        """Verifica a conexão com o terminal MetaTrader 5 da XM.
        Se mt5.terminal_info() retornar nulo ou connected == False,
        executa mt5.initialize(...) automaticamente para auto-reconnect 24/7."""
        if settings.DRY_RUN:
            self.mock = True
            self.connected = False
            return False
        if mt5 is None:
            self.mock = True
            self.connected = False
            return False

        try:
            term = mt5.terminal_info()
            if term is not None and getattr(term, "connected", False):
                self.mock = False
                self.connected = True
                return True
        except Exception:
            pass

        # Auto-reconnect automático à XM
        log.warning("[AUTO-RECONNECT MT5] Terminal desconectado ou nulo. Reconectando à XM...")
        kwargs: Dict[str, Any] = {}
        target_login = self.demo_login or settings.MT5_LOGIN
        target_pass = self.demo_password or settings.MT5_PASSWORD
        target_serv = self.demo_server or settings.MT5_SERVER
        if target_login:
            kwargs = {
                "login": target_login,
                "password": target_pass,
                "server": target_serv,
                "timeout": 15000,
            }

        try:
            mt5.shutdown()
        except Exception:
            pass

        try:
            if mt5.initialize(**kwargs):
                self.mock = False
                self.connected = True
                acc = mt5.account_info()
                log.info("[AUTO-RECONNECT MT5] Reconectado com sucesso à XM! Conta #%s | Servidor: %s",
                         getattr(acc, "login", target_login), getattr(acc, "server", target_serv))
                return True
            else:
                err = mt5.last_error()
                log.warning("[AUTO-RECONNECT MT5] mt5.initialize falhou: %s", err)
                self.mock = True
                self.connected = False
                return False
        except Exception as exc:
            log.error("[AUTO-RECONNECT MT5] Erro durante reconexão: %s", exc)
            self.mock = True
            self.connected = False
            return False

    def shutdown(self) -> None:
        if self.connected and mt5 is not None:
            mt5.shutdown()
            self.connected = False

    # ------------------------------------------------------------------ dados
    def get_rates(self, symbol: str, timeframe: str = settings.TIMEFRAME, n: int = 500) -> pd.DataFrame:
        """Retorna DataFrame com colunas time, open, high, low, close, volume (último candle = em formação)."""
        self.ensure_connection()
        if self.mock:
            return self._mock_rates(symbol, timeframe, n)
        actual_symbol = resolve_symbol(symbol)
        tf = getattr(mt5, f"TIMEFRAME_{timeframe}", mt5.TIMEFRAME_M15)
        mt5.symbol_select(actual_symbol, True)
        raw = mt5.copy_rates_from_pos(actual_symbol, tf, 0, n)
        if raw is None or len(raw) == 0:
            raise RuntimeError(f"Sem candles do MT5 para {symbol} ({actual_symbol}): {mt5.last_error()}")
        df = pd.DataFrame(raw)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["volume"] = df["tick_volume"]
        return df[["time", "open", "high", "low", "close", "volume"]]

    def _mock_rates(self, symbol: str, timeframe: str, n: int) -> pd.DataFrame:
        spec = MOCK_SPECS.get(symbol, DEFAULT_SPEC)
        step = TF_SECONDS.get(timeframe, 900)
        last_k = int(time.time() // step)
        k = np.arange(last_k - n, last_k + 1, dtype=float)  # n+1 pontos para derivar open

        # Regimes suaves (tendência/ciclos) + ruído por candle -> pullbacks, exaustões e rompimentos
        a, s = spec["amp"], spec["seed"]
        level = spec["base"] * np.exp(
            a * (0.05 * np.sin(k / 220 + s) + 0.025 * np.sin(k / 61 + 2 * s) + 0.010 * np.sin(k / 17 + 3 * s)))
        # volatilidade em ciclos (clusters de volatilidade / squeezes)
        vol = spec["vol"] * (1.0 + 0.8 * np.sin(k / 90 + s))
        noise = (_pseudo_rand(k, s) + _pseudo_rand(k, s + 1) + _pseudo_rand(k, s + 2)) / 3 * 1.7
        close = level * (1 + vol * noise)
        open_ = close[:-1]
        close = close[1:]
        k = k[1:]
        wick_up = np.abs(_pseudo_rand(k, s + 3)) * vol[1:] * 0.8
        wick_dn = np.abs(_pseudo_rand(k, s + 4)) * vol[1:] * 0.8
        high = np.maximum(open_, close) * (1 + wick_up)
        low = np.minimum(open_, close) * (1 - wick_dn)
        volume = 100 + 900 * np.abs(_pseudo_rand(k, s + 5))
        times = pd.to_datetime((k * step).astype("int64"), unit="s", utc=True)
        return pd.DataFrame({"time": times, "open": open_, "high": high, "low": low,
                             "close": close, "volume": volume})

    def get_balance(self) -> float:
        if self.mock:
            return settings.MOCK_BALANCE
        info = mt5.account_info()
        return float(info.balance) if info else settings.MOCK_BALANCE

    # ------------------------------------------------------------------ lote
    def calculate_lot(self, symbol: str, entry: float, sl: float, allocation_weight: float = 1.0) -> Dict[str, float]:
        """Lote tal que perda no SL = saldo * RISK_PER_TRADE * allocation_weight."""
        risk_amount = self.get_balance() * settings.RISK_PER_TRADE * max(allocation_weight, 0.0)
        sl_distance = abs(entry - sl)
        if sl_distance <= 0 or risk_amount <= 0:
            return {"volume": 0.0, "risk_amount": 0.0}

        if self.mock:
            contract = MOCK_SPECS.get(symbol, DEFAULT_SPEC)["contract"]
            loss_per_lot = sl_distance * contract
            vol_min, vol_max, vol_step = 0.01, 10.0, 0.01
        else:
            info = mt5.symbol_info(symbol)
            if info is None or info.trade_tick_size <= 0:
                raise RuntimeError(f"symbol_info indisponível para {symbol}")
            loss_per_lot = (sl_distance / info.trade_tick_size) * info.trade_tick_value
            vol_min, vol_max, vol_step = info.volume_min, info.volume_max, info.volume_step

        raw = risk_amount / loss_per_lot if loss_per_lot > 0 else 0.0
        volume = np.floor(raw / vol_step) * vol_step
        volume = float(round(min(max(volume, 0.0), vol_max), 8))
        if volume < vol_min:
            # Risco mínimo do broker excederia o limite: não opera.
            return {"volume": 0.0, "risk_amount": risk_amount}
        return {"volume": round(volume, 2), "risk_amount": round(volume * loss_per_lot, 2)}

    # ------------------------------------------------------------------ ordens
    def get_price(self, symbol: str, side: str) -> float:
        self.ensure_connection()
        if self.mock:
            return float(self._mock_rates(symbol, settings.TIMEFRAME, 2)["close"].iloc[-1])
        actual_symbol = resolve_symbol(symbol)
        mt5.symbol_select(actual_symbol, True)
        tick = mt5.symbol_info_tick(actual_symbol)
        if tick is None:
            raise RuntimeError(f"Sem tick para {symbol} ({actual_symbol})")
        return float(tick.ask if side == "BUY" else tick.bid)

    def execute_order(self, symbol: str, action: str, volume: float, sl: float, tp: float,
                      comment: str = "quant-office", magic: int = 777777,
                      deviation: int = 10, agent_id: Optional[str] = None,
                      db: Optional[Any] = None) -> Dict[str, Any]:
        """Envia ordem a mercado com roteamento dinâmico entre DEMO e REAL (Shadow Trading).
        
        1. Lê trading_mode de system_config (DEMO ou REAL).
        2. Verifica consecutive_losses e status do agent_id em agents_status.
        3. Roteamento:
           - trading_mode == 'DEMO' -> DEMO
           - trading_mode == 'REAL' e losses == 0 e não QUARANTINED -> REAL
           - trading_mode == 'REAL' e (losses > 0 ou QUARANTINED) -> DEMO (Shadow Trading)
        4. Context Switching Seguro:
           - Login na conta Target antes de mt5.order_send()
           - Logo após a execução, fallback reconectando na conta principal.
        """
        action = action.upper()
        if action not in ("BUY", "SELL") or volume <= 0:
            return {"success": False, "comment": "Ordem inválida (lado ou volume incorreto)", "mock": self.mock}

        # 1. Resolver agent_id e carregar banco
        aid = agent_id or (comment if comment and "ops_" in comment else "ops_alpha")
        if db is None:
            from core.database import DatabaseManager
            db = DatabaseManager()

        # 2. Ler trading_mode de system_config
        sys_cfg = db.get_system_config()
        trading_mode = str(sys_cfg.get("trading_mode", "DEMO")).upper()

        # 3. Verificar status e perdas do operador
        agent_stat = db.get_agent_status(aid) or {}
        losses = int(agent_stat.get("consecutive_losses", 0) or 0)
        is_quarantined = (agent_stat.get("current_state") == "QUARANTINED")

        # 4. Roteamento de Risco
        if trading_mode == "DEMO":
            target_account = "DEMO"
            target_creds = (self.demo_login, self.demo_password, self.demo_server)
        elif trading_mode == "REAL" and losses == 0 and not is_quarantined:
            target_account = "REAL"
            target_creds = (self.real_login, self.real_password, self.real_server)
        else:
            # Modo REAL com perdas acumuladas ou quarentena: laboratório de quarentena
            target_account = "DEMO"
            target_creds = (self.demo_login, self.demo_password, self.demo_server)
            log.warning("[SHADOW TRADING] Operador %s (losses=%d, estado=%s) roteado para DEMO (Laboratório de Quarentena).",
                        aid, losses, agent_stat.get("current_state"))

        # Credenciais da conta principal do sistema (para fallback de telemetria)
        if trading_mode == "REAL":
            primary_creds = (self.real_login, self.real_password, self.real_server)
        else:
            primary_creds = (self.demo_login, self.demo_password, self.demo_server)

        price = self.get_price(symbol, action)
        if self.mock:
            ticket_sintetico = int(time.time() * 1000) % 10**9
            log.info("[MOCK ORDER] %s %s %.2f %s | Conta: %s | Modo: %s", aid, action, volume, symbol, target_account, trading_mode)
            return {
                "success": True,
                "ticket": ticket_sintetico,
                "price": price,
                "mock": True,
                "execution_account": target_account,
                "trading_mode": trading_mode,
                "comment": f"SIMULADO [{target_account}]",
            }

        # 5. Context Switching Seguro: Conecta na conta Target antes de mt5.order_send()
        log.info("[ROTEAMENTO MT5] Executando ordem de %s em conta %s (#%s)", aid, target_account, target_creds[0])
        self.login_account(*target_creds)

        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        result = None
        retcode = None
        ret_msg = ""
        success = False

        try:
            for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": float(volume),
                    "type": order_type,
                    "price": price,
                    "sl": float(sl),
                    "tp": float(tp),
                    "deviation": deviation,
                    "magic": magic,
                    "comment": f"{comment[:23]} [{target_account[:4]}]",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": filling,
                }
                result = mt5.order_send(request)
                if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                    log.info("Ordem MT5 executada com sucesso na conta %s: ticket=%s | preço=%.5f | magic=%d",
                             target_account, result.order, result.price, magic)
                    success = True
                    break
        finally:
            # 6. Fallback Obrigatório: Reconecta imediatamente na conta principal
            log.debug("[FALLBACK MT5] Retornando contexto para a conta principal (#%s)...", primary_creds[0])
            self.login_account(*primary_creds)

        if success and result is not None:
            return {
                "success": True,
                "ticket": result.order,
                "price": result.price,
                "mock": False,
                "execution_account": target_account,
                "trading_mode": trading_mode,
                "comment": result.comment,
                "retcode": result.retcode,
            }

        retcode = getattr(result, "retcode", None)
        ret_msg = describe_retcode(retcode)
        last_err = str(mt5.last_error())
        log.error("Ordem MT5 rejeitada na conta %s: %s | retcode=%s | last_error=%s",
                  target_account, ret_msg, retcode, last_err)
        return {
            "success": False,
            "retcode": retcode,
            "retcode_description": ret_msg,
            "mock": False,
            "execution_account": target_account,
            "trading_mode": trading_mode,
            "comment": getattr(result, "comment", ret_msg),
            "last_error": last_err,
        }

    def close_position(self, ticket: int, symbol: Optional[str] = None,
                       volume: Optional[float] = None, comment: str = "close-position",
                       magic: int = 777777, deviation: int = 10) -> Dict[str, Any]:
        """Fecha uma posição aberta no MT5 pelo seu ticket ou simulação."""
        if self.mock:
            log.info("Posição %s fechada em modo simulação.", ticket)
            return {"success": True, "ticket": ticket, "mock": True, "comment": "POSIÇÃO FECHADA (SIMULADO)"}

        positions = mt5.positions_get(ticket=ticket)
        if not positions or len(positions) == 0:
            log.warning("Posição MT5 #%s não encontrada para encerramento.", ticket)
            return {"success": False, "comment": f"Posição #{ticket} não encontrada", "mock": False}

        pos = positions[0]
        sym = symbol or pos.symbol
        vol = float(volume or pos.volume)
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = self.get_price(sym, "SELL" if pos.type == mt5.ORDER_TYPE_BUY else "BUY")

        result = None
        for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": sym,
                "volume": vol,
                "type": close_type,
                "price": price,
                "deviation": deviation,
                "magic": magic,
                "comment": comment[:30],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling,
            }
            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                log.info("Posição MT5 #%s encerrada com sucesso.", ticket)
                return {"success": True, "ticket": result.order, "price": result.price,
                        "mock": False, "comment": result.comment, "retcode": result.retcode}

        retcode = getattr(result, "retcode", None)
        ret_msg = describe_retcode(retcode)
        log.error("Falha ao fechar posição MT5 #%s: %s (retcode=%s)", ticket, ret_msg, retcode)
        return {
            "success": False,
            "retcode": retcode,
            "retcode_description": ret_msg,
            "mock": False,
            "comment": getattr(result, "comment", ret_msg),
        }

    # ------------------------------------------------------------------ sincronização de conta e ordens
    def sync_account_and_positions(self, db: Any = None) -> dict:
        """
        Sincroniza informações da conta MT5 (saldo, equity, margem, floating PnL, total TP, total SL)
        e posições/deals com o Supabase (tabelas mt5_account_status e trades_history).
        Garante conexão na conta definida em system_config (DEMO ou REAL).
        """
        if db is None:
            from core.database import DatabaseManager
            db = DatabaseManager()

        self.ensure_connection()

        sys_cfg = db.get_system_config()
        mode = str(sys_cfg.get("trading_mode", "DEMO")).upper()
        if mode == "REAL":
            target_login = self.real_login
            target_password = self.real_password
            target_server = self.real_server
        else:
            target_login = self.demo_login
            target_password = self.demo_password
            target_server = self.demo_server

        # Garante que o terminal está operando na conta padrão do modo ativo
        if not self.mock and mt5 is not None and self.connected:
            self.login_account(target_login, target_password, target_server)

        if self.mock or mt5 is None or not self.connected:
            # Modo Simulado / Sem conexão: reporta status sem injetar trades sintéticos
            account_data = {
                "balance": float(settings.MOCK_BALANCE if settings.DRY_RUN else 0.0),
                "equity": float(settings.MOCK_BALANCE if settings.DRY_RUN else 0.0),
                "floating_pnl": 0.0,
                "free_margin": float(settings.MOCK_BALANCE if settings.DRY_RUN else 0.0),
                "margin_level": 0.0,
                "total_tp_gain": 0.0,
                "total_sl_loss": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "is_connected": False,
            }
            db.sync_mt5_account(account_data)
            return account_data

        # --- MODO LIVE REAL MT5 ---
        info = mt5.account_info()
        if not info:
            log.warning("Falha ao obter mt5.account_info()")
            return {}

        balance = float(info.balance)
        equity = float(info.equity)
        free_margin = float(info.margin_free)
        margin_level = float(info.margin_level) if info.margin > 0 else 0.0

        positions = mt5.positions_get()
        floating_pnl = 0.0
        if positions:
            for pos in positions:
                floating_pnl += float(pos.profit)
                pos_comment = str(pos.comment or "")
                exec_acc = "DEMO" if "[DEMO" in pos_comment else mode
                db.upsert_trade({
                    "ticket_mt5": int(pos.ticket),
                    "symbol": pos.symbol,
                    "order_type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                    "volume": float(pos.volume),
                    "entry_price": float(pos.price_open),
                    "current_price": float(pos.price_current),
                    "sl": float(pos.sl),
                    "tp": float(pos.tp),
                    "profit_usd": float(pos.profit),
                    "status": "OPEN",
                    "exit_reason": "OPEN",
                    "dry_run": False,
                    "execution_account": exec_acc,
                })

        from_date = datetime.now() - timedelta(days=30)
        deals = mt5.history_deals_get(from_date, datetime.now())
        total_tp_gain = 0.0
        total_sl_loss = 0.0
        win_count = 0
        loss_count = 0

        if deals:
            for d in deals:
                if d.entry == mt5.DEAL_ENTRY_OUT:
                    profit = float(d.profit)
                    reason = "TP_HIT" if profit > 0 else "SL_HIT"
                    if profit > 0:
                        total_tp_gain += profit
                        win_count += 1
                    elif profit < 0:
                        total_sl_loss += profit
                        loss_count += 1

                    ticket_id = int(d.position_id or d.ticket)
                    deal_type_str = "SELL" if getattr(d, "type", 0) == getattr(mt5, "DEAL_TYPE_BUY", 0) else "BUY"
                    existing = db._select("trades_history", eq={"ticket_mt5": ticket_id}, limit=1)
                    agent_id = existing[0].get("agent_id") if (existing and existing[0].get("agent_id")) else (
                        d.comment if (getattr(d, "comment", None) and "ops_" in d.comment) else "ops_alpha"
                    )
                    order_type = existing[0].get("order_type") if (existing and existing[0].get("order_type")) else deal_type_str

                    entry_price = float(existing[0].get("entry_price") or d.price) if existing else float(d.price)
                    sl_val = float(existing[0].get("sl") or 0.0) if existing else 0.0
                    tp_val = float(existing[0].get("tp") or 0.0) if existing else 0.0
                    d_comment = str(d.comment or "")
                    exec_acc = existing[0].get("execution_account") if (existing and existing[0].get("execution_account")) else (
                        "DEMO" if "[DEMO" in d_comment else mode
                    )

                    db.upsert_trade({
                        "ticket_mt5": ticket_id,
                        "agent_id": agent_id,
                        "symbol": d.symbol,
                        "order_type": order_type,
                        "volume": float(d.volume),
                        "entry_price": entry_price,
                        "sl": sl_val,
                        "tp": tp_val,
                        "close_price": float(d.price),
                        "current_price": float(d.price),
                        "profit_usd": profit,
                        "status": "CLOSED",
                        "exit_reason": reason,
                        "dry_run": False,
                        "closed_at": datetime.now(timezone.utc).isoformat(),
                        "execution_account": exec_acc,
                    })

                    # Saída da Quarentena por Mérito (se acertou trade em Shadow Trading)
                    if profit > 0 and agent_id:
                        agent_stat = db.get_agent_status(agent_id) or {}
                        if agent_stat.get("current_state") == "QUARANTINED" or (agent_stat.get("consecutive_losses", 0) or 0) > 0:
                            log.info("[SAÍDA POR MÉRITO - MT5 DEAL] Agente %s acertou TP no Shadow Trading! Promovido de volta ao Risco Real.", agent_id)
                            db.update_agent_status(
                                agent_id,
                                "IDLE",
                                "Saída da Quarentena por Mérito! Take Profit confirmado pelo MT5. Retornando ao Risco Real!",
                                weight=1.0,
                                extra={"quarantine_until": None, "consecutive_losses": 0}
                            )

        account_data = {
            "balance": balance,
            "equity": equity,
            "floating_pnl": floating_pnl,
            "free_margin": free_margin,
            "margin_level": margin_level,
            "total_tp_gain": total_tp_gain,
            "total_sl_loss": total_sl_loss,
            "win_count": win_count,
            "loss_count": loss_count,
            "is_connected": True,
        }
        db.sync_mt5_account(account_data)
        return account_data


def sync_account_and_positions(db: Any = None, bridge: Optional[MT5Bridge] = None) -> dict:
    """Função utilitária para sincronização global do MT5 com o Supabase."""
    if bridge is None:
        bridge = MT5Bridge()
    return bridge.sync_account_and_positions(db)

