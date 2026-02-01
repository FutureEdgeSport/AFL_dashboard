# Data Pipeline Module
# Provides compute functions to move Excel formula logic into Python
#
# Phases:
#   1. Team Ladders (compute_ratings.py, compute_team_summary.py)
#   2. Team Summary (compute_team_summary.py)
#   3. Player Summary (compute_player_summary.py)
#   4. List Ladder / Age Profiles (compute_list_ladder.py)

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

from .compute_team_summary import (
    compute_team_summary,
    compute_team_ladders,
)

from .compute_player_summary import (
    compute_player_summary,
    compute_career_average,
    compute_last_n_years_average,
    load_all_season_data,
    load_squads_data,
    load_contract_data,
    load_draft_data,
)

from .compute_list_ladder import (
    compute_list_ladder,
    compute_list_ladder_l2,
    compute_list_ladder_career,
    compute_age_profile,
    compute_age_profile_2yr,
    compute_age_profile_1yr,
    RATING_TIERS,
    POSITIONS,
    AGE_BANDS,
)

__all__ = [
    # compute_ratings
    "get_player_seasons",
    "get_team_seasons",
    "parse_table_with_detected_header",
    "compute_team_category_rankings",
    "load_team_block",
    "compute_last_n_from_matches",
    "compute_player_summary_from_seasons",
    "compare_to_excel_snapshot",
    # compute_team_summary
    "compute_team_summary",
    "compute_team_ladders",
    # compute_player_summary
    "compute_player_summary",
    "compute_career_average",
    "compute_last_n_years_average",
    "load_all_season_data",
    "load_squads_data",
    "load_contract_data",
    "load_draft_data",
    # compute_list_ladder
    "compute_list_ladder",
    "compute_list_ladder_l2",
    "compute_list_ladder_career",
    "compute_age_profile",
    "compute_age_profile_2yr",
    "compute_age_profile_1yr",
    "RATING_TIERS",
    "POSITIONS",
    "AGE_BANDS",
]
