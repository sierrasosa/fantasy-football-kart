from datetime import datetime, timedelta
from typing import Any, Dict
from zoneinfo import ZoneInfo

from helpers import sleeper_api

APP_TIMEZONE = ZoneInfo("America/Los_Angeles")
DAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def get_current_nfl_context() -> Dict[str, Any]:
    """
    Returns the live NFL week, season, and weekday metadata from Sleeper.
    Falls back to the local date if the API does not respond with data.
    """
    nfl_state = sleeper_api.get_nfl_state() or {}
    now = datetime.now(APP_TIMEZONE)

    current_weekday = now.weekday()
    week = nfl_state.get("week") or 1
    display_week = nfl_state.get("display_week") or 1
    season = now.year - 1 #nfl_state.get("season") or now.year
    season_type = nfl_state.get("season_type") or "regular"

    return {
        "now": now,
        "weekday": current_weekday,
        "day_name": DAY_NAMES[current_weekday],
        "week": int(week),
        "display_week": int(display_week),
        "season": season,
        "season_type": season_type,
    }


def build_weekly_timing_context(
    now: datetime,
    actual_weekday: int,
    actual_week: int,
    selected_week: int,
    active_weekday: int,
    active_week: int,
    use_test_timing: bool = False,
) -> dict[str, Any]:
    """Resolve simulated NFL timing values, availability, and UI messages."""
    simulated_now = now + timedelta(days=active_weekday - actual_weekday)
    day_name = DAY_NAMES[active_weekday]
    drops_open = active_week > 1 and active_weekday >= 1
    item_use_deadline_passed = active_weekday >= 3
    show_item_details = (
        selected_week < active_week
        or (
            selected_week == active_week
            and active_weekday in {0, 3, 4, 5, 6}
        )
    )

    if active_week == 1:
        sidebar_message = "No items week 1. You’ll have to win this one the old-fashioned way."
    elif active_weekday == 0:
        sidebar_message = "Item drops reveal Tuesday morning. Check back soon!"
    else:
        sidebar_message = ""

    if active_week == 1:
        announcement = "Welcome to the season! The chaos will begin next week."
    elif active_weekday == 1:
        announcement = "ITEM DROP TODAY! Make your selection by 11:59 PM Wednesday or it will be made for you!"
    elif active_weekday == 2:
        deadline = (simulated_now + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        hours_remaining = round((deadline - simulated_now).total_seconds() / 3600, 1)
        announcement = f"You have {hours_remaining} hours left to use your item!"
    else:
        announcement = "ITEM REVEAL! Check the Weekly Standings tab to see the action!"

    if (
        selected_week == active_week
        and active_weekday in {1, 2}
    ):
        item_details_message = "Item details reveal on Thursday."
    else:
        item_details_message = "Item appears when this week begins."

    timing_matches_live = (
        active_weekday == actual_weekday and active_week == actual_week
    )
    can_lock_in = active_weekday in {1, 2} and (
        timing_matches_live or use_test_timing
    )
    if use_test_timing and can_lock_in and not timing_matches_live:
        lock_in_message = (
            f"Test timing active; locking in will save this play for "
            f"Week {active_week}."
        )
    elif not timing_matches_live:
        lock_in_message = (
            "Timing values differ from live timing; lock-in is disabled."
        )
    elif active_weekday not in {1, 2}:
        lock_in_message = (
            "Lock-in is available Tuesday and Wednesday only; the deadline "
            "is Thursday at 12:00 AM."
        )
    else:
        lock_in_message = ""

    return {
        "now": simulated_now,
        "weekday": active_weekday,
        "day_name": day_name,
        "week": active_week,
        "item_week": active_week,
        "drops_open": drops_open,
        "item_use_deadline_passed": item_use_deadline_passed,
        "allow_lock_in": can_lock_in,
        "lock_in_message": lock_in_message,
        "show_weekly_item_details": show_item_details,
        "item_details_message": item_details_message,
        "sidebar_message": sidebar_message,
        "announcement": announcement,
    }


def get_revealed_item_plays(
    weekly_plays: list[dict],
    timing_context: dict[str, Any],
) -> list[dict]:
    """Return revealed plays, allowing only one NFL Division Bye per week."""
    active_week = int(timing_context["week"])
    active_weekday = int(timing_context["weekday"])
    revealed = [
        (index, play)
        for index, play in enumerate(weekly_plays)
        if int(play.get("week") or 0) < active_week
        or (
            int(play.get("week") or 0) == active_week
            and active_weekday >= 3
        )
    ]
    revealed.sort(
        key=lambda entry: (
            int(entry[1].get("week") or 0),
            str(entry[1].get("created_at") or ""),
            entry[0],
        )
    )

    division_bye_weeks = set()
    effective_indices = set()
    for index, play in revealed:
        week = int(play.get("week") or 0)
        if (
            str(play.get("item_id") or "").upper() == "NFL_DIVISION_BYE"
            and week in division_bye_weeks
        ):
            continue
        if str(play.get("item_id") or "").upper() == "NFL_DIVISION_BYE":
            division_bye_weeks.add(week)
        effective_indices.add(index)

    return [
        play
        for index, play in enumerate(weekly_plays)
        if index in effective_indices
    ]


def resolve_weekly_timing_context(
    live_context: Dict[str, Any],
    selected_week: int,
    use_test_timing: bool,
    test_weekday: int,
    test_week: int,
) -> dict[str, Any]:
    """Use live NFL timing by default, or explicit simulated values for testing."""
    actual_weekday = int(live_context["weekday"])
    actual_week = int(live_context["week"])
    timing_weekday = test_weekday if use_test_timing else actual_weekday
    timing_week = test_week if use_test_timing else actual_week

    return build_weekly_timing_context(
        live_context["now"],
        actual_weekday,
        actual_week,
        selected_week,
        timing_weekday,
        timing_week,
        use_test_timing=use_test_timing,
    )
