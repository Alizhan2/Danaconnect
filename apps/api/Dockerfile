FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 platform && useradd --uid 10001 --gid platform --no-create-home platform
COPY apps/api/requirements.lock.txt ./requirements.lock.txt
RUN pip install --requirement requirements.lock.txt
COPY --chown=10001:10001 apps/api/ ./
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "172.30.0.10,172.30.0.11,172.30.0.12"]
