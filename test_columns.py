import pandas as pd
import sys
sys.path.insert(0, '/Users/marcuswagner/coding/AFL_dashboard')
from data_pipeline.compute_ratings import parse_table_with_detected_header

team_xl = pd.ExcelFile('/Users/marcuswagner/coding/AFL_dashboard/AFL Team Ratings.xlsx')
summary_df = parse_table_with_detected_header(team_xl, '2025 Summary', 'Team')

print("All columns:")
for i, col in enumerate(summary_df.columns):
    print(f"  {i}: {col}")

print("\nLooking for ranking columns:")
for col in summary_df.columns:
    if 'ranking' in col.lower():
        print(f"  {col}: {summary_df[col].head(3).tolist()}")
