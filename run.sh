#!/usr/bin/env bash
# Запуск прототипа одной командой: ./run.sh
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Создаю окружение Python..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

echo "Загружаю выгрузки и считаю допуск..."
python -m app.pipeline

URL="http://127.0.0.1:8000"
echo "Открываю $URL (остановить: Ctrl+C)"
( sleep 2; (open "$URL" 2>/dev/null || xdg-open "$URL" 2>/dev/null || true) ) &
uvicorn app.api:app --port 8000
