"""Input modes and NFL division membership for weekly item plays."""

ITEM_INPUTS = {
    "SHELL": {"mode": "opponent_manager"},
    "TRIPLE_SHELL": {"mode": "opponent_managers", "count": 3},
    "MUSHROOM": {"mode": "bench_player"},
    "NFL_TEAM_BYE": {"mode": "nfl_team"},
    "NFL_DIVISION_BYE": {"mode": "nfl_division"},
    "COIN": {"mode": "none"},
    "NFL_TEAM_SUPERCHARGE": {"mode": "nfl_team"},
    "NFL_DIVISION_SUPERCHARGE": {"mode": "nfl_division"},
    "SNOW_GAME_DOME_GAME": {
        "mode": "position_choice",
        "choices": {"Snow Game (WR)": "WR", "Dome Game (RB)": "RB"},
    },
    "RECALL": {"mode": "recall_player"},
    "HYPERFLEX": {"mode": "nfl_player"},
    "ULTRAFLEX": {"mode": "free_text_player"},
    "GOLDEN_MUSHROOM": {"mode": "none"},
    "SUPERSTAR": {"mode": "starter_player"},
    "BULLET_BILL": {"mode": "starter_player"},
    "SMASH_BALL": {"mode": "dream_lineup"},
    "MASTER_BALL": {"mode": "player_trade"},
}

NFL_DIVISION_TEAMS = {
    "AFC East": ("BUF", "MIA", "NE", "NYJ"),
    "AFC North": ("BAL", "CIN", "CLE", "PIT"),
    "AFC South": ("HOU", "IND", "JAX", "TEN"),
    "AFC West": ("DEN", "KC", "LAC", "LV"),
    "NFC East": ("DAL", "NYG", "PHI", "WAS"),
    "NFC North": ("CHI", "DET", "GB", "MIN"),
    "NFC South": ("ATL", "CAR", "NO", "TB"),
    "NFC West": ("ARI", "LAR", "SF", "SEA"),
}


def format_nfl_division(division: object) -> str:
    """Format a division with its team abbreviations."""
    division_name = str(division or "").strip()
    teams = NFL_DIVISION_TEAMS.get(division_name)
    if not teams:
        return division_name
    return f"{division_name} ({', '.join(teams)})"


NFL_TEAM_NAMES = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}

LINEUP_SLOT_POSITIONS = {
    "QB": ("QB",),
    "RB": ("RB",),
    "WR": ("WR",),
    "TE": ("TE",),
    "K": ("K",),
    "DEF": ("DEF",),
    "DST": ("DEF",),
    "FLEX": ("RB", "WR", "TE"),
    "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("RB", "WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
    "IDP_FLEX": ("DL", "LB", "DB"),
}

NON_STARTER_SLOTS = {"BN", "IR", "TAXI", "RESERVE"}