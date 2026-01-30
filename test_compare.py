import pandas as pd
import sys
sys.path.insert(0, '/Users/marcuswagner/coding/AFL_dashboard')
from data_pipeline.compute_ratings import (
    parse_table_with_detected_header,
    compute_team_category_rankings,
    compare_to_excel_snapshot,
    load_team_ladders_computed,
)

team_xl = pd.ExcelFile('/Users/marcuswagner/coding/AFL_dashboard/AFL Team Ratings.xlsx')

# Load computed ladder
summary_df = parse_table_with_detected_header(team_xl, '2025 Summary', 'Team')
computed_ladder = compute_team_category_rankings(summary_df)

# Load existing Excel ladder for comparison
excel_ladder = team_xl.parse('2025 Ladders')
print("Excel ladder columns:", excel_ladder.columns.tolist())
print("Excel ladder shape:", excel_ladder.shape)

# Show first few rows of each
print("\n=== Computed Ladder (first 5) ===")
print(computed_ladder[['Team', 'Ball Winning Ranking', 'Defence Ranking', 'Overall Rating']].head())

print("\n=== Excel Ladder (first 10 rows raw) ===")
print(excel_ladder.head(10))
