@echo off
REM Claude Code Remote Control na pasta do projeto: comande a VPS por claude.ai/code ou pelo app do Claude.
REM Aberto pelo start_engine.bat. Reinicia sozinho se cair. Feche a janela para desligar.
REM Permissoes no modo padrao: cada comando/edicao pede aprovacao no celular (a VPS opera a conta ao vivo).
cd /d "%~dp0"
set "CLAUDE=%USERPROFILE%\.local\bin\claude.exe"
if not exist "%CLAUDE%" set "CLAUDE=claude"
REM Remote Control exige a assinatura do claude.ai: sem a chave da API NESTA janela (o auditor continua usando a dele).
set "ANTHROPIC_API_KEY="
set "ANTHROPIC_AUTH_TOKEN="
:loop
echo [%date% %time%] Iniciando Remote Control...
"%CLAUDE%" remote-control --remote-control-session-name-prefix QuantOffice
echo [%date% %time%] Remote Control encerrou (codigo %errorlevel%). Reiniciando em 30s...
timeout /t 30 /nobreak >nul
goto loop
