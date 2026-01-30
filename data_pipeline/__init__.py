# Data Pipeline Module
# Provides compute functions to move Excel formula logic into Python

from .compute_ratings import (
    get_player_seasons,
    get_team_seasons,
    parse_table_with_detected_header,
    compute_team_category_rankings,
    load_team_block,
    compute_last_n_from_matches,
    compute_player_summary_from_seasons,
    compare_to_excel_snapshot,
)

__all__ = [
    "get_player_seasons",
    "get_team_seasons",
    "parse_table_with_detected_header",
    "compute_team_category_rankings",
    "load_team_block",
    "compute_last_n_from_matches",
    "compute_player_summary_from_seasons",
    "compare_to_excel_snapshot",
]
