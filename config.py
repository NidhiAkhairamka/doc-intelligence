import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

CHROMA_DIR = os.environ.get("CHROMA_DIR", "./chroma_store")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "50"))
TOP_K = int(os.environ.get("TOP_K", "5"))
SEMANTIC_WEIGHT = float(os.environ.get("SEMANTIC_WEIGHT", "0.6"))
BM25_WEIGHT = float(os.environ.get("BM25_WEIGHT", "0.4"))

# Sonnet for Q&A — best answer quality
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
# Haiku for background agents — 10x faster, good enough for structured JSON
CLAUDE_FAST_MODEL = os.environ.get("CLAUDE_FAST_MODEL", "claude-haiku-4-5")
# Local model — no API cost. Downloads once (~90MB), runs on CPU.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

ADMIN_API_KEY = os.environ["ADMIN_API_KEY"]
DB_PATH = os.environ.get("DB_PATH", "./doc_intelligence.db")

# Observability
LANGCHAIN_API_KEY = os.environ.get("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT = os.environ.get("LANGCHAIN_PROJECT", "doc-intelligence")
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "./mlruns")
