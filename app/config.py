import os
from pathlib import Path
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")
API_BASE = os.getenv("API_BASE", "http://192.168.1.105:1234/v1")
API_KEY = os.getenv("API_KEY", "lm-studio")
MODEL_NAME = os.getenv("MODEL_NAME", "google/gemma-3-4b")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.4"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))

SYSTEM_PROMPT_PATH = os.getenv(
    "SYSTEM_PROMPT_PATH",
    str(BASE_DIR.parent / "system-prompt.txt")
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{(BASE_DIR.parent / 'movie_finder.db').as_posix()}"
)

CHROMA_PATH = os.getenv("CHROMA_PATH", "../chroma_movies")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "movies")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2"
)

RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))

client = OpenAI(base_url=API_BASE, api_key=API_KEY)