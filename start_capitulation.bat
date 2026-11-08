@echo off
REM Agente CAPITULATION (BTCUSD, magic 20261111) com auto-restart. Aberto automaticamente pelo start_engine.bat.
cd /d "%~dp0"
:loop
echo [%date% %time%] Iniciando CAPITULATION...
python run_capitulation.py
if %errorlevel%==3 exit /b 0
echo [%date% %time%] CAPITULATION encerrou (codigo %errorlevel%). Reiniciando em 30s...
timeout /t 30 /nobreak >nul
goto loop
