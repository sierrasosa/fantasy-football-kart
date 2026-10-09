import math
from datetime import datetime, timezone

from game_logic.player_scores import player_score_key


def load_player_score_inputs(
    supabase_client,
    league_id: str,
    through_week: int,
) -> list[dict]:
    """Load commissioner-entered raw player scores for one league."""
    response = (
        supabase_client.table("player_score_inputs")
        .select("week, player_key, player_id, player_name, points")
        .eq("league_id", league_id)
        .lte("week", through_week)
        .execute()
    )
    return response.data or []


def scores_by_week(score_rows: list[dict]) -> dict[int, dict[str, float]]:
    """Convert stored score rows into the scoring engine's week-indexed maps."""
    scores: dict[int, dict[str, float]] = {}
    for row in score_rows:
        try:
            week = int(row["week"])
            points = float(row["points"])
            player_key = str(row["player_key"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid commissioner score record: {row}") from exc
        if not math.isfinite(points):
            raise ValueError(f"Invalid non-finite commissioner score: {row}")
        scores.setdefault(week, {})[player_key] = points
    return scores


def save_player_score_input(
    supabase_client,
    league_id: str,
    week: int,
    player_id: str | None,
    player_name: str,
    points: float,
) -> None:
    """Insert or update a commissioner-provided raw weekly player score."""
    normalized_name = " ".join(player_name.split())
    score_value = float(points)
    if week < 1:
        raise ValueError("Week must be 1 or greater.")
    if not math.isfinite(score_value):
        raise ValueError("Player points must be a finite number.")
    player_key = player_score_key(player_id, normalized_name)
    record = {
        "league_id": league_id,
        "week": week,
        "player_key": player_key,
        "player_id": str(player_id) if player_id else None,
        "player_name": normalized_name,
        "points": score_value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (
        supabase_client.table("player_score_inputs")
        .upsert(
            record,
            on_conflict="league_id,week,player_key",
        )
        .execute()
    )
