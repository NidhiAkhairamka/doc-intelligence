FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF and sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /data is where the Railway Volume is mounted — create subdirs as fallback
RUN mkdir -p /data/chroma_store /data/db /data/mlruns

# Railway sets PORT=8080 at runtime — expose that port
EXPOSE 8080

CMD gunicorn --workers 1 --bind 0.0.0.0:8080 --timeout 120 api:app
