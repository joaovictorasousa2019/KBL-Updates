@echo off
setlocal
where powershell >nul 2>&1 || (
  echo PowerShell nao encontrado.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0PUBLICAR_ATUALIZACAO.ps1" %*
if errorlevel 1 (
  echo.
  echo Falha ao publicar.
  pause
  exit /b 1
)
echo.
echo Publicacao concluida.
pause
