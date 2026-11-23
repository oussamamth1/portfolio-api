FROM python:3.11-slim

# buffalo_s fits Render's 512 MB free plan; use buffalo_l (more accurate) with 2 GB+ RAM.
# The MODEL_NAME env var at runtime picks the model; a model not baked in is downloaded on first start.
ARG MODEL_NAME=buffalo_s
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_ROOT=/models \
    MODEL_NAME=${MODEL_NAME}

# build-essential: insightface compiles a small C extension
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the face model at build time so the server starts fast
RUN python -c "import os; from insightface.app import FaceAnalysis; FaceAnalysis(name=os.environ['MODEL_NAME'], root='/models', allowed_modules=['detection','recognition'], providers=['CPUExecutionProvider'])"

COPY app ./app

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
