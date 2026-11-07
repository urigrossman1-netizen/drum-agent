@echo off
rem The studio in your web browser at http://127.0.0.1:8000 (personal mode: only this
rem computer can reach it). Stop it with Ctrl+C. Set up first with:  py -3.12 scripts\dev_setup.py
rem Extra arguments go to "serve", e.g.  studio.cmd --port 8010
setlocal
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
if not exist "%ROOT%\.venv\Scripts\python.exe" (
  echo Drum Agent is not set up yet. Run:  py -3.12 "%ROOT%\scripts\dev_setup.py"
  exit /b 1
)
set "DRUM_AGENT_LILYPOND=%ROOT%\tools\lilypond\bin\lilypond.exe"
set "TORCH_HOME=%ROOT%\tools\torch"
set "PATH=%ROOT%\tools\ffmpeg\bin;%ROOT%\tools\fluidsynth\bin;%PATH%"
set "DRUM_AGENT_SOUNDFONT=%ROOT%\tools\soundfonts\FluidR3_GM.sf2"
set "DRUM_AGENT_ENV_FILE=%ROOT%\.env"
set "PYTHONUTF8=1"
cd /d "%ROOT%"
"%ROOT%\.venv\Scripts\python.exe" -m drum_agent serve --personal --seed-examples %*
endlocal
