@echo off
REM Agente US100_RSI2_H1 (US100Cash H1, so compra, magic 20261115) com auto-restart. Roda SO em conta DEMO.
REM Kill switch: crie o arquivo state\KILL_US100_RSI2_H1 (zera e nao abre novas) ou kill_switch: true no YAML.
cd /d "%~dp0"
set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%PY%" set "PY=python"
:loop
echo [%date% %time%] Iniciando US100_RSI2_H1...
"%PY%" run_us100_rsi2.py
if %errorlevel%==3 exit /b 0
echo [%date% %time%] US100_RSI2_H1 encerrou (codigo %errorlevel%). Reiniciando em 30s...
timeout /t 30 /nobreak >nul
goto loop
