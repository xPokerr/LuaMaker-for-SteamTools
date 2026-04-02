@echo off
setlocal enabledelayedexpansion
pushd "%~dp0"

REM 1) Chiedo la versione
set /p version=Inserisci versione programma (esempio 1.0.0):

REM 2) Copio main.spec in build.spec
copy "%~dp0main.spec" "%~dp0build.spec" >nul

REM 3) Con PowerShell faccio un replace non–greedy sulla sola riga name='LuaMaker v...', mantenendo la virgola
powershell -NoProfile -Command ^
  "$s = Get-Content -Raw '%~dp0build.spec';" ^
  "$s = $s -replace \"name='LuaMaker v.*?',\",\"name='LuaMaker v%version%',\";" ^
  "Set-Content -Path '%~dp0build.spec' -Value $s"

IF ERRORLEVEL 1 (
  echo Errore durante la modifica del .spec
  pause
  exit /b 1
)

REM 4) Buildo con PyInstaller (l’icon resta nel .spec, quindi verrà applicata)
pyinstaller --clean "%~dp0build.spec"

REM 5) Rimuovo lo spec temporaneo
del "%~dp0build.spec"

popd
pause
