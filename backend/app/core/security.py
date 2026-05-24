import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import bcrypt
from cryptography.fernet import Fernet

DEFAULT_MASTER_KEYS = {"", "change-me-32-byte-fernet-key", "change-me-please"}
DEFAULT_SESSION_SECRETS = {"", "change-me-session-secret", "change-me-please"}


def password_hash(password: str) -> str:
    rounds = int(os.getenv("DATACLAW_BCRYPT_ROUNDS", "12"))
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def fernet_from_master_key(master_key: str) -> Fernet:
    digest = hashlib.sha256(master_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_json(master_key: str, payload: dict[str, Any]) -> str:
    return fernet_from_master_key(master_key).encrypt(json.dumps(payload).encode()).decode()


def decrypt_json(master_key: str, token: str) -> dict[str, Any]:
    return json.loads(fernet_from_master_key(master_key).decrypt(token.encode()).decode())


def sign_session(secret: str, user_id: str, ttl_hours: int = 24) -> str:
    expires = int((datetime.now(UTC) + timedelta(hours=ttl_hours)).timestamp())
    nonce = secrets.token_urlsafe(12)
    body = f"{user_id}.{expires}.{nonce}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_session(secret: str, token: str) -> str | None:
    parts = token.split(".")
    if len(parts) != 4:
        return None
    user_id, expires, nonce, sig = parts
    body = f"{user_id}.{expires}.{nonce}"
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if int(expires) < int(datetime.now(UTC).timestamp()):
        return None
    return user_id


def validate_runtime_secrets(master_key: str, session_secret: str) -> None:
    if master_key in DEFAULT_MASTER_KEYS:
        raise RuntimeError("MASTER_KEY is unset or still uses the default placeholder. Run `dataclaw init`.")
    if session_secret in DEFAULT_SESSION_SECRETS:
        raise RuntimeError("SESSION_SECRET is unset or still uses the default placeholder. Run `dataclaw init`.")


def generate_runtime_env(env_path: Path) -> dict[str, str]:
    master_key = Fernet.generate_key().decode()
    session_secret = secrets.token_urlsafe(48)
    values = {
        "MASTER_KEY": master_key,
        "SESSION_SECRET": session_secret,
    }
    existing = env_path.read_text() if env_path.exists() else ""
    lines = [line for line in existing.splitlines() if not line.startswith(("MASTER_KEY=", "SESSION_SECRET="))]
    lines.extend(f"{key}={value}" for key, value in values.items())
    env_path.write_text("\n".join(lines).rstrip() + "\n")
    env_path.chmod(0o600)
    return values
