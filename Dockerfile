FROM python:3.11-slim

# Install system deps
RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright + Chromium with all deps auto-handled
RUN playwright install --with-deps chromium

# Copy app code
COPY . .

# Create data dirs
RUN mkdir -p data downloads files_cache screenshots

EXPOSE 8080

CMD gunicorn web.app:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --timeout 300 --worker-class sync
