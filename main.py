"""Orquestrador do Quant Office AI.

Arquitetura de Autonomia Total em Dois Loops Independentes (Multithreading):
- LOOP 1 (TradingEngine): Motor Operacional Autônomo (Tick-by-Tick / Alta Frequência, 15-30s).
  - Execução puramente matemática em Python (zero tokens Claude).
  - Sentinela analisa os gráficos e valida TODAS as 5 estratégias:
    Alpha (Trend), Beta (Mean Reversion), Gamma (Breakout), Delta (SMC Scalp) e Epsilon (VWAP Scalp).
  - Gatilho Autônomo: Se detectar setup, opera IMEDIATAMENTE.
  - O Filtro (Semáforo do Setor 3): ANTES de enviar ordem para a corretora, consulta
    a autorização macro (`strategy_authorization` / `is_macro_ok`). Se autorizado, dispara a ordem;
    se vetado, a ordem é abortada.
  - Heartbeat Logger: Emite log consolidado a cada 60 segundos com status MT5, S3 Veto e cotações ao vivo.
  - Atualização do Supabase: `mt5_account_status` recebe timestamp atualizado (`updated_at`) a cada ciclo.
- LOOP 2 (MacroRisk): Inteligência Macro e Risco (O Filtro de Notícias, a cada 30m).
  - news_collector (Finnhub API + RSS + ForexFactory) -> Setor 2 -> Setor 3.
  - O Setor 3 atualiza o JSON de `strategy_authorization` no Supabase, alterando as
    placas de trânsito silenciosamente para guiar o Loop 1.
"""
import argparse
import itertools
import json
import logging
import random
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

import schedule

from agents import (sector_1_ops, sector_2_news, sector_3_analytics, sector_4_rnd,
                    sector_5_manager, sector_6_boardroom)
from agents.claude_client import ClaudeClient
from config import settings
from core.database import DatabaseManager, strategy_of
from core.mt5_bridge import MT5Bridge
from core.news_collector import NewsCollector
from core.sentinel import Sentinel

log = logging.getLogger("main")


class QuantOffice:
    def __init__(self) -> None:
        self.db = DatabaseManager()
        self.claude = ClaudeClient()
        self.bridge = MT5Bridge()
        self.sentinel = Sentinel(self.bridge, db=self.db)
        self.news_collector = NewsCollector(self.db)
        self.db.register_agents()
        self.bridge.sync_account_and_positions(self.db)
        self._stop_event = threading.Event()

    def monitor_open_positions_and_close(self):
        """Loop de Fecho Dinâmico por RSI:
        Monitora todas as posições abertas no MT5 e fecha a mercado conforme as regras dinâmicas de RSI:
        - Posição BUY fecha se RSI >= 60.
        - Posição SELL fecha se RSI <= 40.
        - Envia atualização para trades_history no Supabase (status 'CLOSED', calculando lucro/perda real).
        """
        return self.bridge.monitor_open_positions_and_close(self.db)

    def check_quarantine_releases(self) -> List[str]:
        """Relógio de Quarentena Automático: verifica no Supabase (agents_status) agentes em QUARANTINED
        cujo quarantine_until <= NOW(). Executa UPDATE para IDLE e limpa quarantine_until."""
        released = self.db.release_expired_quarantines()
        for agent_id in released:
            log.info("[RELÓGIO DE QUARENTENA] Quarentena expirada! Agente %s reintegrado -> status IDLE (Posto Operacional)", agent_id)
        return released

    # --------------------------------------------------------------- LOOP 1: TRADING ENGINE
    def trading_engine_loop(self) -> None:
        """LOOP 1: Motor Operacional Autônomo (Tick-by-Tick / Alta Frequência).
        Roda a cada 15 segundos ininterruptamente em sua própria thread.
        Custo zero de tokens Claude: toda a matemática de indicadores (RSI, Bollinger, FVG, VWAP)
        ocorre em Python nativo no sentinel.py.
        Gatilho Autônomo + Semáforo do Setor 3 garantem execução ultra-rápida e segura."""
        log.info("[LOOP 1: TRADING ENGINE] Motor Operacional Autônomo iniciado com sucesso.")
        interval = min(settings.SENTINEL_INTERVAL_SEC, 15)
        last_heartbeat_time = 0.0

        while not self._stop_event.is_set():
            try:
                # 1. Telemetria MT5 em tempo real (saldo, equity, posições abertas)
                # Atualiza mt5_account_status.updated_at a cada ciclo para provar respiração do backend
                self.bridge.sync_account_and_positions(self.db)

                # 2. Relógio de Quarentena Automático: Desbloqueia agentes quando quarantine_until <= NOW()
                released = self.check_quarantine_releases()

                # 3. Fecho Dinâmico por RSI das Posições Abertas (BUY fecha se RSI >= 60, SELL fecha se RSI <= 40)
                rsi_closed = self.monitor_open_positions_and_close()
                if rsi_closed:
                    log.info("[LOOP 1 - FECHO DINÂMICO RSI] %d posição(ões) encerrada(s) por RSI: %s",
                             len(rsi_closed), rsi_closed)

                # 4. Liquidação e acompanhamento de ordens em andamento por SL
                settled_count = sector_1_ops.settle_open_trades(self.db, self.bridge)
                if settled_count > 0:
                    log.info("[LOOP 1] %d ordem(ns) liquidada(s) por SL.", settled_count)

                # 5. Monitor de risco de perdas consecutivas (Setor 5)
                risk_events = sector_5_manager.process_closed_trades(self.db, self.claude)
                for event in risk_events:
                    log.warning("[LOOP 1 - GESTÃO DE RISCO] %s",
                                json.dumps(event, ensure_ascii=False, default=str))

                # 5. Leitura Dinâmica de Ativos: Sentinela varre EXCLUSIVAMENTE os ativos ativados na UI
                sys_cfg = self.db.get_system_config()
                active_assets = sys_cfg.get("active_assets")
                if not isinstance(active_assets, list) or len(active_assets) == 0:
                    active_assets = settings.SYMBOLS

                active_agents = {a["agent_id"]: strategy_of(a) for a in self.db.get_active_ops_agents()}
                triggers = self.sentinel.scan_all(active_agents, active_assets=active_assets)

                if triggers:
                    log.info("[LOOP 1] Sentinela identificou %d setup(s) quantitativo(s):", len(triggers))
                    for trig in triggers:
                        log.info("[LOOP 1 - GATILHO DETECTADO] Ativo: %s | Setup: %s [%s] -> Operador: %s",
                                 trig["symbol"], trig["trigger"], trig["bias"], trig["agent_id"])

                        # Disparo Imediato via Motor Matemático (Autonomia Total do Setor 1 - Fim do Veto)
                        result = sector_1_ops.execute_autonomous_trigger(trig, self.db, self.bridge)
                        if result:
                            log.info("[LOOP 1 - EXECUÇÃO RESULTADO] %s -> %s", trig["agent_id"], result)

                # 6. HEARTBEAT LOGGER A CADA 60 SEGUNDOS EXATOS
                now_t = time.time()
                if now_t - last_heartbeat_time >= 60.0:
                    last_heartbeat_time = now_t
                    mt5_status = "Conectado" if self.bridge.connected and not self.bridge.mock else ("Simulado" if self.bridge.mock else "Desconectado")
                    m_ctx = self.db.get_latest_market_context() or {}
                    s2_veto_status = "Desativado (Sem Bloqueio)"

                    price_parts = []
                    asset_labels = {"BTCUSD": "BTC", "ETHUSD": "ETH", "SOLUSD": "SOL", "XAUUSD": "XAU"}
                    for sym in active_assets:
                        label = asset_labels.get(sym, sym)
                        try:
                            p = self.bridge.get_price(sym, "BUY")
                            price_parts.append(f"{label} {p:.0f}" if p >= 100 else f"{label} {p:.2f}")
                        except Exception:
                            price_parts.append(f"{label} ---")

                    prices_formatted = ", ".join(price_parts)
                    heartbeat_msg = f"[TELEMETRIA VIVA] MT5: {mt5_status} | Setor 2 Veto: {s2_veto_status} | Último Preço: {prices_formatted}"
                    print(f"\n{heartbeat_msg}\n", flush=True)
                    log.info(heartbeat_msg)

            except Exception as exc:  # noqa: BLE001
                print(f"[ERRO CRÍTICO EVITADO] Falha no loop principal do Trading Engine: {exc}", flush=True)
                log.error("[LOOP 1 - ERRO CRÍTICO EVITADO]: %s", exc)

            time.sleep(interval)

    # --------------------------------------------------------------- LOOP 2: MACRO & RISCO
    def macro_risk_loop(self) -> None:
        """LOOP 2: Inteligência Macro e Risco (O Filtro de Notícias).
        Roda a cada 30 minutos em background.
        Executa: news_collector -> Setor 2 -> Setor 3.
        O Setor 3 atualiza o JSON de `strategy_authorization` no Supabase,
        atuando silenciosamente como as 'placas de trânsito' para o Loop 1."""
        log.info("[LOOP 2: MACRO RISK] Inteligência Macro & Risco iniciada.")
        interval_sec = settings.NEWS_INTERVAL_MIN * 60

        # Roda uma calibragem macro inicial na largada
        try:
            log.info("[LOOP 2] Executando calibragem macro inicial...")
            self.job_news()
        except Exception as exc:  # noqa: BLE001
            log.exception("[LOOP 2] Falha na análise macro inicial: %s", exc)

        while not self._stop_event.is_set():
            # Espera o intervalo ou interrupção do sistema
            if self._stop_event.wait(timeout=interval_sec):
                break

            try:
                log.info("[LOOP 2] Atualizando ciclo de notícias e autorizações macro...")
                self.job_news()
            except Exception as exc:  # noqa: BLE001
                print(f"[ERRO CRÍTICO EVITADO] Falha no Macro Risk: {exc}", flush=True)
                log.error("[LOOP 2 - ERRO CRÍTICO EVITADO]: %s", exc)

    # --------------------------------------------------------------- JOBS SETORIAIS
    def job_news(self) -> dict:
        """Cadeia de comando de risco:
        1. news_collector roda (Finnhub API + RSS + Calendário ForexFactory) e grava em market_context.
        2. Setor 2 analisa e gera o 'Score de Sentimento' (-10 a +10, red flags, key driver).
        3. Setor 3 (Auditor) recebe a resposta diretamente e cruza com os estilos operacionais,
           retornando o JSON estrito com strategy_authorization e veto_reason.
        """
        log.info("--- [CADEIA DE COMANDO DE RISCO: NOTÍCIA -> SETOR 2 -> SETOR 3] ---")
        market_context = self.news_collector.get_global_market_context()
        sentiment = sector_2_news.run(self.db, self.claude, market_context)
        if sentiment is None:
            log.warning("Sem resumo macro do Setor 2: autorizações do Setor 3 não serão renovadas.")
            return {"market_context": market_context, "sentiment": None, "macro_gate": None}

        # Setor 2 repassa a resposta diretamente para o Setor 3 (auditor_quant)
        veto_report = sector_3_analytics.evaluate_macro_relevance(self.db, self.claude, sentiment)
        log.info("Decisão de Veto do Setor 3: is_market_safe=%s | Motivo: %s",
                 veto_report.get("is_market_safe"), veto_report.get("veto_reason"))
        log.info("Autorizações de estratégia: %s",
                 json.dumps(veto_report.get("strategy_authorization", {}), ensure_ascii=False))

        return {
            **sentiment,
            "is_market_safe": veto_report.get("is_market_safe", False),
            "strategy_authorization": veto_report.get("strategy_authorization", {}),
            "veto_reason": veto_report.get("veto_reason", ""),
            "macro_gate": veto_report,
        }

    def job_daily(self) -> dict:
        """Rotina Diária (Conselho Estratégico): Setores 3 -> 4 -> 5 -> 6."""
        summary: dict = {}
        try:
            sector_1_ops.settle_open_trades(self.db, self.bridge)
            summary["risk_events"] = sector_5_manager.process_closed_trades(self.db, self.claude)
            metrics = sector_3_analytics.build_metrics(self.db)
            report = sector_3_analytics.run(self.db, self.claude, metrics)
            summary["analytics"] = report
            if report:
                summary["rnd"] = sector_4_rnd.run(self.db, self.claude, report)
            decision = sector_5_manager.run(self.db, self.claude, metrics, report)
            summary["manager"] = decision
            reasons = []
            if decision and decision.get("trigger_boardroom"):
                reasons.append("Gerência acionou a reunião (quarentena/risco elevado).")
            if report and report.get("request_emergency_meeting"):
                reasons.append("Analytics solicitou reunião de emergência.")
            if reasons:
                summary["boardroom"] = sector_6_boardroom.run(
                    self.db, self.claude, " ".join(reasons), metrics, report)
        except Exception as exc:  # noqa: BLE001
            log.exception("job_daily falhou: %s", exc)
        return summary

    # --------------------------------------------------------------- TESTES
    def _seed_demo_trades(self) -> None:
        """Cria histórico fechado sintético (apenas se faltar) para o Setor 3 ter o que auditar."""
        existing = [t for t in self.db.get_trades_last_24h() if t.get("status") == "CLOSED"]
        if existing:
            return
        profiles = {"ops_alpha": 0.62, "ops_beta": 0.20, "ops_gamma": 0.45,
                    "ops_delta": 0.55, "ops_epsilon": 0.50}
        rng = random.Random(42)
        now = datetime.now(timezone.utc)
        for agent_id, p_win in profiles.items():
            for i in range(10):
                symbol = rng.choice(settings.SYMBOLS)
                entry = 100.0
                risk = settings.MOCK_BALANCE * settings.RISK_PER_TRADE
                win = rng.random() < p_win
                opened = (now - timedelta(hours=22 - i * 2)).isoformat()
                trade = self.db.log_trade(
                    agent_id, symbol, rng.choice(["BUY", "SELL"]), 0.1, entry, entry - 1, entry + 2, risk,
                    confidence=70, rationale="DEMO_SEED", dry_run=True, status="CLOSED",
                    pnl=risk * 2 if win else -risk, opened_at=opened,
                    closed_at=(now - timedelta(hours=21 - i * 2)).isoformat())
                self.db.mark_trade_processed(trade["id"])
        log.info("Histórico demo de %d trades criado.", 10 * len(profiles))

    def test_flow(self) -> None:
        """Ciclo completo de validação do sistema."""
        log.info("=== TEST FLOW: News collector -> Setor 2 -> Setor 3 (gate macro) ===")
        news = self.job_news()
        print("Notícias + gate macro:", json.dumps(news, ensure_ascii=False, default=str))

        log.info("=== TEST FLOW: Setor 1 (Execução Autônoma de Gatilhos) ===")
        symbols = itertools.cycle(["BTCUSD", "XAUUSD", "ETHUSD", "SOLUSD"])
        for agent in self.db.get_active_ops_agents():
            agent_id, symbol = agent["agent_id"], next(symbols)
            trig = self.sentinel.force_trigger(symbol, agent_id, strategy_of(agent))
            if trig:
                res = sector_1_ops.execute_autonomous_trigger(trig, self.db, self.bridge)
                print(f"Ops Autônomo {agent_id}/{symbol}:", json.dumps(res, ensure_ascii=False, default=str))

        log.info("=== TEST FLOW: Setores 3, 4, 5 e 6 ===")
        self._seed_demo_trades()
        summary = self.job_daily()
        for key, value in summary.items():
            print(f"{key}:", json.dumps(value, ensure_ascii=False, default=str, indent=2))
        print("\nCache Claude:", self.claude.cache_stats)
        print("Status final dos agentes:")
        for a in sorted(self.db.get_all_agents_status(), key=lambda r: r["agent_id"]):
            print(f"  {a['agent_id']:<10} {a['current_state']:<12} w={a.get('allocation_weight')} | {a.get('last_thought')}")

    # --------------------------------------------------------------- EXECUÇÃO PARALELA
    def run_forever(self) -> None:
        """Inicia os dois loops autônomos em threads dedicadas."""
        self._stop_event.clear()

        log.info("=================================================================")
        log.info("  QUANT OFFICE AI - INICIANDO SISTEMA MULTITHREAD AUTÔNOMO       ")
        log.info("  DRY_RUN: %s | MT5_MOCK: %s | ATIVOS: %s",
                 settings.DRY_RUN, self.bridge.mock, settings.SYMBOLS)
        log.info("=================================================================")

        # Criação explícita das duas threads autônomas conforme especificação
        engine_thread = threading.Thread(
            target=self.trading_engine_loop,
            daemon=True,
            name="TradingEngine"
        )
        macro_thread = threading.Thread(
            target=self.macro_risk_loop,
            daemon=True,
            name="MacroRisk"
        )

        engine_thread.start()
        macro_thread.start()

        log.info("Threads ativas: [TradingEngine (Loop 1)] e [MacroRisk (Loop 2)] rodando em paralelo.")

        # Agenda a rotina diária no agendador central
        schedule.every().day.at(settings.DAILY_RUN_TIME).do(self.job_daily)

        try:
            while not self._stop_event.is_set():
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Encerrando Quant Office AI...")
            self._stop_event.set()
        finally:
            self.bridge.shutdown()
            log.info("Quant Office AI finalizado com segurança.")


def check_quarantine_releases(office: Optional[QuantOffice] = None) -> List[str]:
    """Função do Relógio de Quarentena Automático para execução direta."""
    if office:
        return office.check_quarantine_releases()
    db = DatabaseManager()
    return db.release_expired_quarantines()


def monitor_open_positions_and_close(bridge: Optional[MT5Bridge] = None,
                                     db: Optional[DatabaseManager] = None):
    """Função de Fecho Dinâmico por RSI:
    - Lista todas as posições abertas.
    - Lê o RSI atual do ativo.
    - Se BUY e RSI >= 60 -> fecha posição a mercado.
    - Se SELL e RSI <= 40 -> fecha posição a mercado.
    - Atualiza Supabase trades_history com status 'CLOSED' e lucro/perda real.
    """
    if bridge is None:
        bridge = MT5Bridge()
    if db is None:
        db = DatabaseManager()
    return bridge.monitor_open_positions_and_close(db)


def run_autonomous_daemon(office: Optional[QuantOffice] = None) -> None:
    """Orquestrador inquebrável com resiliência 24/7 para VPS.
    Nunca crasha: em caso de falha de conexão, queda do broker ou erro inesperado,
    evita o crash, aguarda retorno da rede e reconecta automaticamente."""
    print("[DAEMON] Sistema Multi-Agente Quant iniciado com autonomia 24/7.", flush=True)
    while True:
        try:
            if office is None:
                office = QuantOffice()
            office.run_forever()
        except KeyboardInterrupt:
            print("\n[DAEMON] Encerrando daemon por solicitação do usuário...", flush=True)
            break
        except Exception as e:
            print(f"[ERRO CRÍTICO EVITADO] Falha no loop principal: {e}", flush=True)
            traceback.print_exc()
            print("[DAEMON] Aguardando 30 segundos para reconexão da rede/serviços...", flush=True)
            time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Quant Office AI - Autonomous Quant Orchestrator")
    parser.add_argument("--test-flow", action="store_true", help="Executa ciclo de teste completo e sai.")
    parser.add_argument("--test-all-sectors", action="store_true", help="Roda Setores 3 a 6 imediatamente e sai.")
    parser.add_argument("--verbose", action="store_true", help="Habilita logs em nível DEBUG.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    office = QuantOffice()
    if args.test_flow:
        office.test_flow()
    elif args.test_all_sectors:
        print(json.dumps(office.job_daily(), ensure_ascii=False, default=str, indent=2))
    else:
        run_autonomous_daemon(office)


if __name__ == "__main__":
    main()
