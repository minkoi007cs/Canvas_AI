FROM python:3.11-slim

# Install system deps for Playwright + Chromium
RUN apt-get update && apt-get install -y \
    wget curl gnupg unzip \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libpangocairo-1.0-0 libcairo2 libx11-6 libx11-xcb1 libxcb1 \
    libxext6 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium
RUN playwright install chromium

# Copy app code
COPY . .

# Create data dirs
RUN mkdir -p data downloads files_cache screenshots

EXPOSE 8080

CMD ["gunicorn", "web.app:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "300", "--worker-class", "sync"]
