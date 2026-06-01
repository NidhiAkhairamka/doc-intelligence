FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF and sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-download the embedding model so it's baked into the image.
# Without this, Railway downloads ~90MB at startup and times out (502).
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

# Create data dirs
RUN mkdir -p /app/chroma_store /app/data /app/mlruns

# Railway injects PORT at runtime — expose it
EXPOSE ${PORT:-5000}

CMD ["python", "api.py"]
