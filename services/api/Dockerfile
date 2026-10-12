FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/services/api
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY services/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api/butler ./butler
COPY seed /app/seed
RUN useradd --uid 10001 --create-home butler && mkdir /app/.runtime && chown butler /app/.runtime
USER butler
EXPOSE 8000
CMD ["uvicorn", "butler.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
