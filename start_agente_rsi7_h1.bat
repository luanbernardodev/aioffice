@echo off
REM Agente RSI7_H1 (BTCUSD H1, magic 20261114) com auto-restart. Roda SO em conta DEMO (trava no codigo).
REM Kill switch: crie o arquivo state\KILL_AGENTE_RSI7_H1 (zera e nao abre novas) ou kill_switch: true no YAML.
cd /d "%~dp0"
:loop
echo [%date% %time%] Iniciando AGENTE_RSI7_H1...
python run_agente_rsi7_h1.py
if %errorlevel%==3 exit /b 0
echo [%date% %time%] AGENTE_RSI7_H1 encerrou (codigo %errorlevel%). Reiniciando em 30s...
timeout /t 30 /nobreak >nul
goto loop
