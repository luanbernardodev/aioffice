@echo off
REM Motor deterministico na conta DEMO 309673774 (ordens reais na demo), com auto-restart.
REM Requisitos: MT5 aberto e logado na demo 309673774, botao "Algo Trading" ligado.
REM NAO rode o main.py antigo ao mesmo tempo, nem este motor em outra maquina na mesma conta.
cd /d "%~dp0"
start "SWEEP48" cmd /c start_sweep48.bat
start "CAPITULATION" cmd /c start_capitulation.bat
start "RSI20" cmd /c start_rsi20.bat
start "AGENTE_RSI7_H1" cmd /c start_agente_rsi7_h1.bat
:loop
echo [%date% %time%] Iniciando motor (DEMO, DRY_RUN=False)...
python run_engine.py --live-demo
echo [%date% %time%] Motor encerrou (codigo %errorlevel%). Reiniciando em 30s... (feche a janela para parar)
timeout /t 30 /nobreak >nul
goto loop
