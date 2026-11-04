@echo off
rem Drum Agent on this computer, from the repository: the studio in its own window
rem (python -m drum_agent app, personal mode). Set up first with:  py -3.12 scripts\dev_setup.py
rem Settings and API keys come from the repository's .env (copy of .env.example).
setlocal
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
if not exist "%ROOT%\.venv\Scripts\pythonw.exe" (
  echo Drum Agent is not set up yet. Run:  py -3.12 "%ROOT%\scripts\dev_setup.py"
  pause
  exit /b 1
)
set "DRUM_AGENT_TOOLS=%ROOT%\tools"
set "DRUM_AGENT_ENV_FILE=%ROOT%\.env"
set "PYTHONUTF8=1"
start "" "%ROOT%\.venv\Scripts\pythonw.exe" -m drum_agent app
endlocal
