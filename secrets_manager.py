# secrets_manager.py
import os
import subprocess
import json
import time
from filelock import FileLock
from pathlib import Path


def _load_env_from_file():
    """Load variables from .env files into the process environment (does not overwrite existing vars)."""
    candidates = [
        f'.env.{os.getenv("FLASK_ENV", "dev")}',
        ".env",
        ".env.local",
    ]
    for filename in candidates:
        path = Path(filename)
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


branch = os.getenv("FLASK_ENV", "dev")

# Load .env file on startup (covers local dev without Docker env injection)
_load_env_from_file()

# BWS is optional. When BWS_ACCESS_TOKEN is set, secrets are fetched from
# Bitwarden Secrets Manager. Otherwise, get_secret() falls back to plain
# environment variables — the default path for self-hosters.
bws_session = os.getenv("BWS_ACCESS_TOKEN")

SECRETS_CACHE = {}
CACHE_EXPIRATION_SECONDS = 300
LOCK_FILE = "secrets.lock"


def _update_secrets_cache():
    with FileLock(LOCK_FILE):
        try:
            output = subprocess.check_output(["bws", "secret", "list"], text=True)
            secrets = json.loads(output)
            current_time = time.time()
            for secret in secrets:
                SECRETS_CACHE[secret["key"].lower()] = {
                    "value": secret["value"],
                    "expires": current_time + CACHE_EXPIRATION_SECONDS,
                }
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Failed to retrieve secrets from Bitwarden: {e}")


def get_secret(secret_key, field_name=None):
    """Retrieve a secret value.

    Resolution order:
      1. Plain environment variable matching secret_key (uppercased).
         This is the recommended path for self-hosters — just set env vars
         or populate a .env file (see .env.example).
      2. Bitwarden Secrets Manager (BWS), when BWS_ACCESS_TOKEN is configured.
         This is the maintainer path used in the hosted deployment.

    Raises ValueError if the secret cannot be found via either method.
    """
    # 1. Plain env var (self-hoster / community path)
    env_val = os.getenv(secret_key.upper())
    if env_val is not None:
        return env_val

    # 2. Bitwarden Secrets Manager (optional, maintainer path)
    if not bws_session:
        raise ValueError(
            f"Secret '{secret_key}' not found. "
            f"Set the {secret_key.upper()} environment variable, "
            f"or configure BWS_ACCESS_TOKEN to use Bitwarden Secrets Manager."
        )

    secret_key_lower = secret_key.lower()
    if secret_key_lower in SECRETS_CACHE and time.time() < SECRETS_CACHE[secret_key_lower]["expires"]:
        secret = SECRETS_CACHE[secret_key_lower]["value"]
        return secret.get(field_name) if field_name else secret

    _update_secrets_cache()

    if secret_key_lower in SECRETS_CACHE:
        secret = SECRETS_CACHE[secret_key_lower]["value"]
        return secret.get(field_name) if field_name else secret

    raise ValueError(f"Secret '{secret_key}' not found in environment variables or Bitwarden.")
