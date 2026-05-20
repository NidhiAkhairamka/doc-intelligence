FROM python:3.11-slim

WORKDIR /app

# Install system deps for PyMuPDF and sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data dirs so volumes mount cleanly
RUN mkdir -p /app/chroma_store /app/data /app/mlruns

EXPOSE 5000

CMD ["python", "api.py"]
