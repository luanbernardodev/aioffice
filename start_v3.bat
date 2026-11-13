@echo off
REM Agentes v3 da competicao (config/agente_v3_competicao.yaml), com auto-restart. Aberto pelo start_engine.bat.
cd /d "%~dp0"
set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%PY%" set "PY=python"
:loop
echo [%date% %time%] Iniciando agentes V3...
"%PY%" run_v3_agents.py
if %errorlevel%==3 exit /b 0
echo [%date% %time%] V3 encerrou (codigo %errorlevel%). Reiniciando em 30s...
timeout /t 30 /nobreak >nul
goto loop
