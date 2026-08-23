import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# --- НАСТРОЙКИ GIT И РЕПОЗИТОРИЯ ---
GIT_REPO_PATH = os.getenv("GIT_REPO_PATH", "./")
GIT_DEFAULT_BRANCH = os.getenv("GIT_DEFAULT_BRANCH", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Ssazurov/git-doc-sync-agent")

# --- НАСТРОЙКИ ХРАНЕНИЯ ДАННЫХ ---
DOCS_DIR = os.getenv("DOCS_DIR", "./docs")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./db")
SYNC_STATE_FILE = os.getenv("SYNC_STATE_FILE", "./db/sync_state.json")

# --- НАСТРОЙКИ ЧАНКИНГА И АНАЛИЗА ---
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
CHUNK_MODE = os.getenv("CHUNK_MODE", "smart")  # "smart" или "simple"

# --- НАСТРОЙКИ ИИ (OLLAMA & OPENAI) ---
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip('/')
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b-instruct-q4_K_M")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "ollama")  # "ollama" или "openai"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# --- НАСТРОЙКИ РЕРАНКИНГА ---
RERANK_PROVIDER = os.getenv("RERANK_PROVIDER", "none")  # "none", "cohere", "jina"
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
COHERE_RERANK_MODEL = os.getenv("COHERE_RERANK_MODEL", "rerank-multilingual-v3.0")
JINA_API_KEY = os.getenv("JINA_API_KEY", "")
JINA_RERANK_MODEL = os.getenv("JINA_RERANK_MODEL", "jina-reranker-v2-base-multilingual")

# --- СИСТЕМНЫЕ ПРОМПТЫ ---
SYSTEM_PROMPT_DETECTOR = os.getenv(
    "SYSTEM_PROMPT_DETECTOR",
    "Вы — эксперт по анализу кода. Сравни изменения в коде с заголовками документов и предложи оптимальный маппинг."
)
