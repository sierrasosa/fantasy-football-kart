from datetime import datetime
from typing import Any, Dict

from helpers import sleeper_api


def get_current_nfl_context() -> Dict[str, Any]:
    """
    Returns the live NFL week, season, and weekday metadata from Sleeper.
    Falls back to the local date if the API does not respond with data.
    """
    nfl_state = sleeper_api.get_nfl_state() or {}
    now = datetime.now()

    day_names = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    current_weekday = now.weekday()
    week = nfl_state.get("week") or 1
    display_week = nfl_state.get("display_week") or 1
    season = now.year - 1 #nfl_state.get("season") or now.year
    season_type = nfl_state.get("season_type") or "regular"

    return {
        "now": now,
        "weekday": current_weekday,
        "day_name": day_names[current_weekday],
        "week": int(week),
        "display_week": int(display_week),
        "season": season,
        "season_type": season_type,
    }


def get_weekly_event_context(supabase_client: Any, selected_week: int) -> Dict[str, Any]:
    """
    Checks the league_events table for the selected week and resolves an event status.
    The app can decide how to render the returned message; this function keeps the
    logic centralized and day-aware.
    """
    context = get_current_nfl_context()
    current_day = context["day_name"]

    active_event = None
    try:
        event_res = supabase_client.table("league_events").select("*").eq("week", selected_week).execute()
        events = event_res.data or []
        active_event = events[0] if events else None
    except Exception:
        active_event = None

    if active_event is None:
        return {
            "active_event": None,
            "message": "No special league event for this week.",
            "status": "normal",
            "current_day": current_day,
            "selected_week": selected_week,
        }

    event_name = active_event.get("event_name") or "League Event"
    description = active_event.get("description") or ""

    if current_day in {"Tuesday", "Wednesday", "Thursday"}:
        status = "active"
        message = f"{event_name} is active this week — check the event panel for the current matchup window."
    elif current_day in {"Friday", "Saturday", "Sunday"}:
        status = "weekend"
        message = f"{event_name} remains in effect for Week {selected_week}."
    else:
        status = "early_week"
        message = f"{event_name} is scheduled for Week {selected_week}; details are available in the event panel."

    return {
        "active_event": active_event,
        "event_name": event_name,
        "description": description,
        "message": message,
        "status": status,
        "current_day": current_day,
        "selected_week": selected_week,
    }
