FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data downloads files_cache screenshots

EXPOSE 8080

CMD ["gunicorn", "web.app:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "300", "--log-level", "debug", "--access-logfile", "-", "--error-logfile", "-"]
