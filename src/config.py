"""
Centralized configuration — reads from env vars, with AWS Secrets Manager fallback.
All sensitive values are sourced from Secrets Manager; no secrets in K8s secrets or CI.
"""
import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)


def _load_secret(secret_id: str) -> dict:
    """Fetch a secret from AWS Secrets Manager by name or ARN. Returns {} on any failure."""
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1"))
        response = client.get_secret_value(SecretId=secret_id)
        return json.loads(response["SecretString"])
    except Exception as e:
        log.debug("Secrets Manager fetch skipped for %s: %s", secret_id, e)
        return {}


def _env_or_secret(env_key: str, secret_path: str, secret_field: str, default: str = "") -> str:
    """Return env var value if set, otherwise look up in Secrets Manager."""
    val = os.getenv(env_key, "")
    if val:
        return val
    secret = _load_secret(secret_path)
    return secret.get(secret_field, default)


def _get_db_password() -> str:
    """
    DB password resolution order:
    1. DB_PASSWORD env var (local dev / CI override)
    2. /ticketing/prod/db-credentials  (manual secret)
    3. RDS-managed secret via RDS_SECRET_ARN env var (auto-rotates with RDS)
    """
    val = os.getenv("DB_PASSWORD", "")
    if val:
        return val
    _sm_prefix = os.getenv("SECRETS_MANAGER_PREFIX", "/ticketing/prod")
    secret = _load_secret(f"{_sm_prefix}/db-credentials")
    if secret.get("password"):
        return secret["password"]
    # RDS_SECRET_ARN is set in the ConfigMap; IRSA already has /rds!* access
    rds_arn = os.getenv("RDS_SECRET_ARN", "")
    if rds_arn:
        return _load_secret(rds_arn).get("password", "")
    return ""


_SM_PREFIX = os.getenv("SECRETS_MANAGER_PREFIX", "/ticketing/prod")


class Config:
    # ── Database ──────────────────────────────────────────────────────────────
    DB_HOST     = os.getenv("DB_HOST", "localhost")
    DB_PORT     = int(os.getenv("DB_PORT", 5432))
    DB_NAME     = os.getenv("DB_NAME", "tickets_db")
    DB_USER     = os.getenv("DB_USER", "ticketing_admin")
    DB_PASSWORD = _get_db_password()
    DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", 2))
    DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", 10))
    DB_SSL_MODE = os.getenv("DB_SSL_MODE", "require")   # 'require' on RDS, 'disable' locally

    # ── LLM ───────────────────────────────────────────────────────────────────
    GROQ_API_KEY       = _env_or_secret("GROQ_API_KEY", f"{_SM_PREFIX}/groq-api-key", "api_key")
    OPENROUTER_API_KEY = _env_or_secret("OPENROUTER_API_KEY", f"{_SM_PREFIX}/openrouter-api-key", "api_key")
    LLM_PROVIDER    = os.getenv("LLM_PROVIDER", "groq")
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", 0.1))
    LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", 4096))

    METADATA_EXTRACTION_MODEL = os.getenv("METADATA_EXTRACTION_MODEL", "llama-3.1-8b-instant")
    CLASSIFICATION_MODEL      = os.getenv("CLASSIFICATION_MODEL", "llama-3.3-70b-versatile")

    # ── Semantic search ───────────────────────────────────────────────────────
    SEMANTIC_MODEL_NAME       = "all-MiniLM-L6-v2"
    SIMILAR_TICKETS_LIMIT     = int(os.getenv("SIMILAR_TICKETS_LIMIT", 20))
    SIMILARITY_THRESHOLD      = float(os.getenv("SIMILARITY_THRESHOLD", 0.3))
    SEMANTIC_SEARCH_BATCH_SIZE = int(os.getenv("SEMANTIC_SEARCH_BATCH_SIZE", 500))

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_HOST     = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT     = int(os.getenv("REDIS_PORT", 6379))
    REDIS_AUTH     = _env_or_secret("REDIS_AUTH", f"{_SM_PREFIX}/redis-credentials", "auth_token")
    REDIS_SSL      = os.getenv("REDIS_SSL", "true").lower() == "true"
    REDIS_ENABLED  = os.getenv("REDIS_ENABLED", "true").lower() == "true"

    # ── SQS ───────────────────────────────────────────────────────────────────
    AWS_REGION             = os.getenv("AWS_REGION", "ap-south-1")
    SQS_NOTIFICATION_URL   = os.getenv("SQS_NOTIFICATION_URL", "")
    SQS_LLM_URL            = os.getenv("SQS_LLM_URL", "")
    SQS_ENABLED            = os.getenv("SQS_ENABLED", "true").lower() == "true"

    # ── Email ─────────────────────────────────────────────────────────────────
    SUPPORT_EMAIL              = _env_or_secret("SUPPORT_EMAIL", f"{_SM_PREFIX}/app-config", "support_email")
    SUPPORT_EMAIL_APP_PASSWORD = _env_or_secret(
        "SUPPORT_EMAIL_APP_PASSWORD", f"{_SM_PREFIX}/email-credentials", "app_password"
    )
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT   = int(os.getenv("SMTP_PORT", 465))

    # ── Observability ─────────────────────────────────────────────────────────
    # "custom"   → stores traces in local PostgreSQL llm_traces table (default, free, unlimited)
    # "langfuse" → sends to cloud.langfuse.com (free 50K obs/month; set keys below)
    # "none"     → no tracing
    OBSERVABILITY_PROVIDER = os.getenv("OBSERVABILITY_PROVIDER", "custom")

    # LangFuse keys (only needed when OBSERVABILITY_PROVIDER=langfuse)
    LANGFUSE_PUBLIC_KEY = _env_or_secret("LANGFUSE_PUBLIC_KEY", f"{_SM_PREFIX}/langfuse-credentials", "public_key")
    LANGFUSE_SECRET_KEY = _env_or_secret("LANGFUSE_SECRET_KEY", f"{_SM_PREFIX}/langfuse-credentials", "secret_key")
    LANGFUSE_HOST       = _env_or_secret("LANGFUSE_HOST",       f"{_SM_PREFIX}/langfuse-credentials", "host") or "https://cloud.langfuse.com"

    # ── API authentication ────────────────────────────────────────────────────
    API_KEYS_RAW = _env_or_secret("API_KEYS", f"{_SM_PREFIX}/api-keys", "keys")
    JWT_SECRET   = _env_or_secret("JWT_SECRET", f"{_SM_PREFIX}/app-config", "jwt_secret") or "changeme-set-a-strong-secret-in-production"

    @classmethod
    def get_valid_api_keys(cls) -> set:
        """Return set of valid API keys. Accepts comma-separated env var or JSON array."""
        raw = cls.API_KEYS_RAW
        if not raw:
            return set()
        if raw.startswith("["):
            try:
                return set(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return {k.strip() for k in raw.split(",") if k.strip()}

    # ── App ───────────────────────────────────────────────────────────────────
    PORT        = int(os.getenv("PORT", 8000))
    HOST        = os.getenv("HOST", "0.0.0.0")
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL   = os.getenv("LOG_LEVEL", "INFO")

    # ── Secrets Manager prefix ────────────────────────────────────────────────
    SECRETS_MANAGER_PREFIX = _SM_PREFIX

    @classmethod
    def get_db_config(cls) -> dict:
        config = {
            "host":     cls.DB_HOST,
            "port":     cls.DB_PORT,
            "database": cls.DB_NAME,
            "user":     cls.DB_USER,
            "password": cls.DB_PASSWORD,
        }
        if cls.DB_SSL_MODE != "disable":
            config["sslmode"] = cls.DB_SSL_MODE
        return config

    @classmethod
    def validate(cls):
        errors = []
        if cls.LLM_PROVIDER == "groq" and not cls.GROQ_API_KEY:
            errors.append("GROQ_API_KEY is not set (check env or Secrets Manager)")
        if cls.LLM_PROVIDER == "openrouter" and not cls.OPENROUTER_API_KEY:
            errors.append("OPENROUTER_API_KEY is not set (check env or Secrets Manager)")
        if not cls.DB_PASSWORD:
            errors.append("DB_PASSWORD is not set (check env or Secrets Manager)")
        if errors:
            raise ValueError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
        return True
