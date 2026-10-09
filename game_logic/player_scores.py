import re
import unicodedata


def normalize_player_name(player_name: str) -> str:
    """Normalize a player name for matching and score-input identity."""
    decomposed = unicodedata.normalize("NFKD", player_name).casefold()
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_marks).strip()


def player_score_key(
    player_id: object | None = None,
    player_name: str | None = None,
) -> str:
    """Return a stable score key, preferring Sleeper IDs over names."""
    if player_id is not None and str(player_id).strip():
        return f"id:{str(player_id).strip()}"

    normalized_name = normalize_player_name(player_name or "")
    if not normalized_name:
        raise ValueError("A player ID or player name is required.")
    return f"name:{normalized_name}"
