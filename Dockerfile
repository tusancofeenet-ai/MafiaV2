# Stable runtime for aiogram 2.x + aiohttp 3.8.x.
FROM python:3.11-slim

WORKDIR /Mafia

COPY requirements.txt .

RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Canonical production entrypoint.
CMD ["python", "-u", "player_runtime_entry.py"]
