FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-impress libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir 'pydantic>=2.13,<3' 'pypdf>=6,<7' 'python-pptx>=1,<2' 'docling>=2,<3' 'pypdfium2==5.14.0'
WORKDIR /app
COPY server/__init__.py server/__init__.py
COPY server/ingestion server/ingestion
COPY server/lessons/contracts.py server/lessons/contracts.py
COPY server/lessons/__init__.py server/lessons/__init__.py
COPY server/providers/base.py server/providers/base.py
COPY server/providers/__init__.py server/providers/__init__.py
COPY server/script.py server/script.py
COPY server/visuals.py server/visuals.py
# Bake Docling/OCR model assets during the controlled image build. Runtime has
# no network; a missing model is a setup failure, never an automatic download.
RUN docling-tools models download --output-dir /models
RUN useradd --uid 10001 --create-home parser && chmod -R a+rX /models
ENV HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
USER 10001
ENTRYPOINT ["python", "-m", "server.ingestion.parse_worker"]
