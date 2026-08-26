"""
Embedding generation for RAG using a local sentence-transformer model or deterministic fallback.
"""
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, List, Optional

import numpy as np
import requests
import urllib3

# Disable SSL warnings for corporate proxy environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configure HuggingFace Hub settings
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

EMBEDDING_DIMENSION = 384
MODELS_PATH = os.getenv("MODELS_PATH", "/models")
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "BAAI/bge-small-en-v1.5",
)
HF_EMBEDDING_API_TOKEN = os.getenv("HF_EMBEDDING_API_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN") or os.getenv("HF_API_TOKEN")
HF_EMBEDDING_API_URL = os.getenv(
    "HF_EMBEDDING_API_URL",
    "https://router.huggingface.co/hf-inference/models",
).rstrip("/")
LOCAL_EMBEDDING_MODEL_PATH = os.getenv(
    "LOCAL_EMBEDDING_MODEL_PATH",
    "./hg_model/all-MiniLM-L6-v2",
)
USE_SENTENCE_TRANSFORMERS = os.getenv(
    "USE_SENTENCE_TRANSFORMERS",
    "true",
).lower() not in {"0", "false", "no", "off"}
USE_REMOTE_EMBEDDING_API = os.getenv(
    "USE_REMOTE_EMBEDDING_API",
    "false",
).lower() not in {"0", "false", "no", "off"}

if USE_SENTENCE_TRANSFORMERS:
    try:
        from sentence_transformers import SentenceTransformer
        SENTENCE_TRANSFORMERS_AVAILABLE = True
        logger.info("✓ sentence_transformers module available")
    except ImportError:
        SENTENCE_TRANSFORMERS_AVAILABLE = False
        logger.warning("✗ sentence_transformers module NOT available")
else:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.info("sentence_transformers disabled by configuration; using deterministic embeddings only")

logger.info(f"📦 MODELS_PATH: {MODELS_PATH}")
logger.info(f"📦 EMBEDDING_MODEL_NAME: {EMBEDDING_MODEL_NAME}")
logger.info(f"📦 HF_HOME: {os.getenv('HF_HOME')}")
logger.info(f"📦 TRANSFORMERS_CACHE: {os.getenv('TRANSFORMERS_CACHE')}")
logger.info(
    "Embedding config: model_name=%s cache_root=%s local_model_path=%s sentence_transformers_available=%s use_sentence_transformers=%s use_remote_api=%s",
    EMBEDDING_MODEL_NAME,
    MODELS_PATH,
    LOCAL_EMBEDDING_MODEL_PATH,
    SENTENCE_TRANSFORMERS_AVAILABLE,
    USE_SENTENCE_TRANSFORMERS,
    USE_REMOTE_EMBEDDING_API,
)

# Global sentence-transformer model cache
_SENTENCE_TRANSFORMER_MODEL = None

def _candidate_model_paths() -> List[Path]:
    """Return possible cache locations for the configured sentence-transformer model."""
    root = Path(MODELS_PATH)
    model_name = EMBEDDING_MODEL_NAME
    model_slug = model_name.split("/")[-1]
    normalized_slug = model_name.replace("/", "--")

    candidates = [
        root / "sentence-transformers" / model_name,
        root / "sentence-transformers" / model_slug,
        root / model_name,
        root / model_slug,
        root / f"models--{normalized_slug}",
        root / f"models--sentence-transformers--{normalized_slug}",
    ]

    for config_path in root.rglob("config.json"):
        candidates.append(config_path.parent)

    # Remove duplicates while preserving order.
    unique_candidates: List[Path] = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(candidate)
    return unique_candidates


def _load_sentence_transformer():
    """Load the local sentence-transformer model from the configured local directory path."""
    global _SENTENCE_TRANSFORMER_MODEL

    if not USE_SENTENCE_TRANSFORMERS:
        logger.warning(
            "Sentence-transformers disabled by configuration; using deterministic embeddings only"
        )
        return None

    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        logger.warning("sentence_transformers not available, will use fallback embedding")
        return None

    if _SENTENCE_TRANSFORMER_MODEL is not None:
        logger.debug("✓ Returning cached sentence-transformer model")
        return _SENTENCE_TRANSFORMER_MODEL

    local_model_path = Path(LOCAL_EMBEDDING_MODEL_PATH)
    logger.info(
        "Checking for local sentence-transformer model at %s",
        local_model_path,
    )

    if local_model_path.exists() and (local_model_path / "config.json").exists():
        try:
            logger.info(
                "✓ LOCAL MODEL FOUND: Loading %s from %s",
                EMBEDDING_MODEL_NAME,
                local_model_path,
            )
            _SENTENCE_TRANSFORMER_MODEL = SentenceTransformer(str(local_model_path))
            logger.info(
                "✓ Successfully loaded %s from local path %s",
                EMBEDDING_MODEL_NAME,
                local_model_path,
            )
            return _SENTENCE_TRANSFORMER_MODEL
        except Exception as exc:
            logger.warning(
                "Could not load sentence-transformer from local path %s: %s",
                local_model_path,
                exc,
            )

    candidate_paths = _candidate_model_paths()
    logger.info(
        "Searching for sentence-transformer cache under %s; candidates=%s",
        MODELS_PATH,
        [str(path) for path in candidate_paths],
    )

    for candidate in candidate_paths:
        config_file = candidate / "config.json"
        if config_file.exists():
            try:
                logger.info(
                    "✓ LOCAL MODEL FOUND: Loading %s from %s",
                    EMBEDDING_MODEL_NAME,
                    candidate,
                )
                _SENTENCE_TRANSFORMER_MODEL = SentenceTransformer(str(candidate))
                logger.info(
                    "✓ Successfully loaded %s from local cache at %s",
                    EMBEDDING_MODEL_NAME,
                    candidate,
                )
                return _SENTENCE_TRANSFORMER_MODEL
            except Exception as exc:
                logger.warning(
                    "Could not load sentence-transformer from %s: %s",
                    candidate,
                    exc,
                )

    try:
        logger.info(
            "No local cache directory matched; trying to load %s from the cache root %s",
            EMBEDDING_MODEL_NAME,
            MODELS_PATH,
        )
        _SENTENCE_TRANSFORMER_MODEL = SentenceTransformer(
            EMBEDDING_MODEL_NAME,
            cache_folder=MODELS_PATH,
        )
        logger.info(
            "✓ Successfully loaded %s from model name using cache root %s",
            EMBEDDING_MODEL_NAME,
            MODELS_PATH,
        )
        return _SENTENCE_TRANSFORMER_MODEL
    except Exception as exc:
        logger.warning(
            "⚠ No usable sentence-transformer cache found under %s: %s",
            MODELS_PATH,
            exc,
        )
        logger.warning(
            "Sentence-transformer model cache missing; using deterministic fallback"
        )
        logger.warning(
            "💡 To use sentence-transformers, pre-download the model to the MODELS_PATH or set LOCAL_EMBEDDING_MODEL_PATH"
        )
        logger.warning(
            "   Falling back to deterministic embedding generation"
        )
        return None

def _normalize_embedding_payload(payload: Any) -> Optional[List[float]]:
    if payload is None:
        return None

    if isinstance(payload, list):
        if payload and isinstance(payload[0], (int, float)):
            return [float(value) for value in payload]
        if payload and isinstance(payload[0], list):
            first = payload[0]
            if first and isinstance(first[0], (int, float)):
                return [float(value) for value in first]

    if isinstance(payload, dict):
        if "embedding" in payload and isinstance(payload["embedding"], list):
            return [float(value) for value in payload["embedding"] if isinstance(value, (int, float))]
        if "data" in payload and isinstance(payload["data"], list):
            data = payload["data"]
            if data and isinstance(data[0], dict):
                item = data[0].get("embedding")
                if isinstance(item, list):
                    return [float(value) for value in item if isinstance(value, (int, float))]

    return None


def _remote_sentence_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding using the Hugging Face Inference API when a local model is not available."""
    prompt = (text or "").strip()
    if not prompt:
        print("[EMBEDDING] Hugging Face remote embedding skipped: empty text")
        return None
    if not USE_REMOTE_EMBEDDING_API:
        print("[EMBEDDING] Hugging Face remote embedding skipped: USE_REMOTE_EMBEDDING_API is false")
        return None

    if not HF_EMBEDDING_API_TOKEN:
        print(
            "[EMBEDDING] Hugging Face remote embedding skipped: missing HF_EMBEDDING_API_TOKEN"
        )
        logger.warning(
            "HF_EMBEDDING_API_TOKEN is not set; skipping remote embedding API call"
        )
        return None

    try:
        print(
            f"[EMBEDDING] Using Hugging Face remote transformer model={EMBEDDING_MODEL_NAME} url={HF_EMBEDDING_API_URL}"
        )
        logger.info(
            "Calling Hugging Face embedding API for model=%s via %s",
            EMBEDDING_MODEL_NAME,
            HF_EMBEDDING_API_URL,
        )
        response = requests.post(
            f"{HF_EMBEDDING_API_URL}/{EMBEDDING_MODEL_NAME}",
            headers={
                "Authorization": f"Bearer {HF_EMBEDDING_API_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"inputs": prompt, "normalize": True, "truncate": True},
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        embedding = _normalize_embedding_payload(payload)
        if embedding is None:
            logger.warning(
                "Remote embedding API returned an unexpected payload: %s",
                payload,
            )
            return None

        print(
            f"[EMBEDDING] Hugging Face remote transformer succeeded for model={EMBEDDING_MODEL_NAME} dimensions={len(embedding)}"
        )
        logger.info(
            "✓ Generated embedding via remote Hugging Face API using %s (%s dimensions)",
            EMBEDDING_MODEL_NAME,
            len(embedding),
        )
        return embedding
    except Exception as exc:
        print(
            f"[EMBEDDING] Hugging Face remote transformer failed for model={EMBEDDING_MODEL_NAME}: {exc}"
        )
        logger.warning(
            "Remote embedding API call failed for %s: %s",
            EMBEDDING_MODEL_NAME,
            exc,
        )
        return None


def _sentence_transformer_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding using the local sentence-transformer model or a remote API fallback."""
    model = _load_sentence_transformer()
    if model is not None:
        try:
            prompt = (text or "").strip()
            if not prompt:
                return None

            print(
                f"[EMBEDDING] Using local sentence-transformer model={EMBEDDING_MODEL_NAME} text_len={len(prompt)}"
            )
            logger.debug(f"Using {EMBEDDING_MODEL_NAME} for embedding (text length: {len(prompt)})")
            embedding = model.encode(prompt, convert_to_numpy=True)
            logger.debug(f"✓ Generated embedding using {EMBEDDING_MODEL_NAME} ({len(embedding)} dimensions)")
            print(
                f"[EMBEDDING] Local sentence-transformer succeeded for model={EMBEDDING_MODEL_NAME} dimensions={len(embedding)}"
            )
            return [float(value) for value in embedding]
        except Exception as e:
            print(
                f"[EMBEDDING] Local sentence-transformer failed for model={EMBEDDING_MODEL_NAME}: {e}"
            )
            logger.error(f"✗ Sentence-transformer embedding failed: {e}", exc_info=True)

    remote_embedding = _remote_sentence_embedding(text)
    if remote_embedding is not None:
        return remote_embedding

    print(
        "[EMBEDDING] Falling back to deterministic embedding because no transformer model returned a vector"
    )
    logger.debug("sentence-transformer model unavailable, will use fallback")
    return None


def _fallback_embedding(text: str) -> List[float]:
    """Generate a deterministic local embedding when the transformer model is unavailable."""
    vector = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())

    if not tokens:
        return vector.tolist()

    for index, token in enumerate(tokens):
        digest = hashlib.sha256(f"{index}:{token}".encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % EMBEDDING_DIMENSION
        weight = 1.0 + (digest[4] / 255.0)
        vector[bucket] += weight

    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector /= norm
    return vector.tolist()


def _resize_embedding(values: List[float], target_dimension: int = EMBEDDING_DIMENSION) -> List[float]:
    if not values:
        return [0.0] * target_dimension

    vector = np.array(values, dtype=np.float32)
    if vector.shape[0] == target_dimension:
        return vector.tolist()

    if vector.shape[0] > target_dimension:
        chunks = np.array_split(vector, target_dimension)
        resized = np.array([float(chunk.mean()) if len(chunk) else 0.0 for chunk in chunks], dtype=np.float32)
    else:
        resized = np.zeros(target_dimension, dtype=np.float32)
        resized[: vector.shape[0]] = vector

    norm = float(np.linalg.norm(resized))
    if norm > 0:
        resized /= norm
    return resized.tolist()


def _ollama_embedding(text: str) -> Optional[List[float]]:
    """Deprecated compatibility hook kept for older call sites."""
    return _sentence_transformer_embedding(text)


def generate_embedding(text: str) -> List[float]:
    """Generate a text embedding using the model when available, otherwise fall back deterministically."""
    embedding = _sentence_transformer_embedding(text)
    if embedding is not None:
        logger.debug("Embedding generated via sentence-transformers for text length=%s", len(text or ""))
        return embedding

    logger.debug("Using deterministic local embedding fallback for text length=%s", len(text or ""))
    return _fallback_embedding(text)


def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for multiple texts using the local model or remote API when available."""
    model = _load_sentence_transformer()
    if model is not None and texts:
        try:
            logger.info(
                "Batch embedding generation for %s texts using %s",
                len(texts),
                EMBEDDING_MODEL_NAME,
            )
            embeddings = model.encode(texts, convert_to_numpy=True)
            logger.info("Batch sentence-transformer embeddings succeeded for %s texts", len(texts))
            return [[float(value) for value in row] for row in embeddings]
        except Exception as e:
            logger.warning("Batch sentence-transformer embedding failed: %s", e)

    if texts and USE_REMOTE_EMBEDDING_API and HF_EMBEDDING_API_TOKEN:
        logger.info(
            "Batch embedding generation for %s texts using remote Hugging Face API",
            len(texts),
        )
        remote_embeddings = []
        for text in texts:
            embedding = _remote_sentence_embedding(text)
            if embedding is None:
                remote_embeddings.append(_fallback_embedding(text))
            else:
                remote_embeddings.append(embedding)
        return remote_embeddings

    logger.info(
        "Batch embedding generation for %s texts using deterministic local fallback (remote API disabled)",
        len(texts),
    )
    return [_fallback_embedding(text) for text in texts]


def embedding_dimension() -> int:
    """Return the embedding dimension for pgvector setup."""
    return EMBEDDING_DIMENSION
