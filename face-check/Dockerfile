FROM python:3.11-slim

# buffalo_s fits Render's 512 MB free plan; buffalo_l (more accurate) needs 2 GB+ RAM.
ARG MODEL_NAME=buffalo_s
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_ROOT=/models \
    MODEL_NAME=${MODEL_NAME} \
    OMP_NUM_THREADS=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download only the detection + recognition models from the InsightFace release
COPY download_models.py .
RUN python download_models.py buffalo_s buffalo_l

COPY app ./app

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
