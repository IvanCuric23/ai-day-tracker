@echo off
setlocal
rem the whole block is read before powershell (and its git pull) can rewrite this file
(
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
  set RC=!ERRORLEVEL!
  pause
  exit /b !RC!
)
