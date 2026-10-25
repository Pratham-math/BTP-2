FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libcairo2-dev libpango1.0-dev pkg-config build-essential fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-platform.txt && useradd --uid 10001 --create-home worker && mkdir -p /app/.run && chown worker /app/.run
COPY server/ ./server/
USER 10001
ENTRYPOINT ["python", "-m", "server.worker"]
CMD ["--queue", "generation"]
