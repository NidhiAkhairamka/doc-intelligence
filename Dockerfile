FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF and sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data dirs
RUN mkdir -p /app/chroma_store /app/data /app/mlruns

# Railway sets PORT=8080 at runtime — expose that port
EXPOSE 8080

CMD ["python", "api.py"]
