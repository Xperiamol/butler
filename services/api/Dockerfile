FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/services/api
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY services/api/requirements.txt services/api/requirements-semantic.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# 可选的中文语义能力（约 570 MB 词向量）：docker build --build-arg WITH_SEMANTIC=1 ...
ARG WITH_SEMANTIC=0
RUN if [ "$WITH_SEMANTIC" = "1" ]; then pip install --no-cache-dir -r requirements-semantic.txt; fi
COPY services/api/butler ./butler
COPY seed /app/seed
RUN useradd --uid 10001 --create-home butler && mkdir /app/.runtime && chown butler /app/.runtime
USER butler
EXPOSE 8000
CMD ["uvicorn", "butler.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
