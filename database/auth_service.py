import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone


PIN_ATTEMPT_LIMIT = 5
PIN_ATTEMPT_WINDOW = timedelta(minutes=15)


def hash_pin(pin: str) -> str:
    """Hash a PIN with a per-value salt and PBKDF2."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored_hash: str) -> bool:
    """Verify current salted hashes and legacy SHA-256 PIN hashes."""
    if not isinstance(stored_hash, str):
        return False
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt_hex, digest_hex = stored_hash.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256", pin.encode(), bytes.fromhex(salt_hex), int(rounds)
            )
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (ValueError, TypeError):
            return False
    legacy_hash = hashlib.sha256(pin.encode()).hexdigest()
    return hmac.compare_digest(legacy_hash, stored_hash)


def generate_pin() -> str:
    """Generate a 10-digit one-time PIN for a newly initialized manager."""
    return f"{secrets.randbelow(10_000_000_000):010d}"


def create_login_session(supabase_client, user_id: str, league_id: str, lifetime_days: int = 30) -> tuple[str, datetime]:
    """Create a revocable persistent session and return its raw cookie token."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=lifetime_days)
    supabase_client.table("login_sessions").insert({
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "user_id": str(user_id),
        "league_id": str(league_id),
        "expires_at": expires_at.isoformat(),
    }).execute()
    return token, expires_at


def get_login_session(supabase_client, token: str) -> dict | None:
    """Resolve a cookie token to a live server-side login session."""
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    rows = (
        supabase_client.table("login_sessions")
        .select("token_hash, user_id, league_id, expires_at")
        .eq("token_hash", token_hash)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    session = rows[0]
    expires_at = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        supabase_client.table("login_sessions").delete().eq("token_hash", token_hash).execute()
        return None
    return session


def revoke_login_session(supabase_client, token: str) -> None:
    """Revoke a persistent session using the raw token from this browser."""
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        supabase_client.table("login_sessions").delete().eq("token_hash", token_hash).execute()


def update_login_session_league(supabase_client, token: str, league_id: str) -> None:
    """Persist the selected active league for a remembered browser session."""
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        supabase_client.table("login_sessions").update({
            "league_id": str(league_id),
        }).eq("token_hash", token_hash).execute()


def pin_is_rate_limited(supabase_client, user_id: str) -> bool:
    """Check the shared per-user PIN failure window; fail closed on DB errors."""
    try:
        rows = (
            supabase_client.table("login_attempts")
            .select("failed_attempts, window_started_at")
            .eq("user_id", user_id)
            .execute()
            .data
            or []
        )
        if not rows:
            return False
        started = datetime.fromisoformat(
            rows[0]["window_started_at"].replace("Z", "+00:00")
        )
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - started >= PIN_ATTEMPT_WINDOW:
            return False
        return int(rows[0]["failed_attempts"]) >= PIN_ATTEMPT_LIMIT
    except Exception:
        return True


def record_failed_pin(supabase_client, user_id: str) -> None:
    """Increment or restart this user's failed PIN attempt window."""
    now = datetime.now(timezone.utc)
    rows = (
        supabase_client.table("login_attempts")
        .select("failed_attempts, window_started_at")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    attempts = 0
    started = now
    if rows:
        started = datetime.fromisoformat(
            rows[0]["window_started_at"].replace("Z", "+00:00")
        )
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if now - started < PIN_ATTEMPT_WINDOW:
            attempts = int(rows[0]["failed_attempts"])
        else:
            started = now
    supabase_client.table("login_attempts").upsert(
        {
            "user_id": user_id,
            "failed_attempts": attempts + 1,
            "window_started_at": started.isoformat(),
        },
        on_conflict="user_id",
    ).execute()