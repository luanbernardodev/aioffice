@echo off
REM Motor deterministico na conta DEMO 309673774 (ordens reais na demo), com auto-restart.
REM Requisitos: MT5 aberto e logado na demo 309673774, botao "Algo Trading" ligado.
REM NAO rode o main.py antigo ao mesmo tempo, nem este motor em outra maquina na mesma conta.
cd /d "%~dp0"
start "SWEEP48" cmd /c start_sweep48.bat
REM 12/11: CAPITULATION desligado (capitulation.enabled=false)
start "RSI20" cmd /c start_rsi20.bat
REM 12/11: AGENTE_RSI7_H1 desligado (config/agente_rsi7_h1.yaml enabled=false)
:loop
echo [%date% %time%] Iniciando motor (DEMO, DRY_RUN=False)...
python run_engine.py --live-demo
set EXITCODE=%errorlevel%
echo [%date% %time%] Motor encerrou (codigo %EXITCODE%). Reiniciando em 30s... (feche a janela para parar)
if not exist logs mkdir logs
echo %date% %time% ^| start_engine.bat: python saiu com codigo %EXITCODE% >> logs\restarts.log
timeout /t 30 /nobreak >nul
goto loop
