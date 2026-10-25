#!/usr/bin/env bash
# Runs every time the codespace starts: start the studio on port 8000 (in the background).
cd "$(dirname "$0")/.."
up() { [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health)" != "000" ]; }
if up; then
  echo "Drum Agent Studio is already running on port 8000"
  exit 0
fi
setsid nohup python -m drum_agent serve --host 0.0.0.0 --port 8000 --seed-examples > /tmp/drum-agent.log 2>&1 < /dev/null &
for _ in $(seq 1 90); do
  up && break
  sleep 1
done
if up; then
  echo "Drum Agent Studio is running on port 8000 (log: /tmp/drum-agent.log)"
else
  echo "The studio did not start; see /tmp/drum-agent.log" >&2
  tail -20 /tmp/drum-agent.log >&2
fi
