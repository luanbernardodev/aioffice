@echo off
REM Agente SWEEP48 (BTCUSD M5, magic 20261110) com auto-restart. Aberto automaticamente pelo start_engine.bat.
cd /d "%~dp0"
:loop
echo [%date% %time%] Iniciando SWEEP48...
python run_sweep48.py
if %errorlevel%==3 exit /b 0
echo [%date% %time%] SWEEP48 encerrou (codigo %errorlevel%). Reiniciando em 30s...
timeout /t 30 /nobreak >nul
goto loop
