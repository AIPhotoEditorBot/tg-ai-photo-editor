# Используем стабильный Python 3.11 (Pillow и многое другое собирается надёжно)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Кэшируем установку requirements
COPY requirements.txt .

# Установим системные зависимости для сборки Pillow и других пакетов, затем установим python-зависимости
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       gcc \
       libjpeg-dev \
       zlib1g-dev \
       libwebp-dev \
       libopenjp2-7-dev \
       libpng-dev \
       ca-certificates \
    && python -m pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем код
COPY . .

# Запуск (бот работает в режиме polling, порт не обязателен)
CMD ["python", "main.py"]
