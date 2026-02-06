#!/usr/bin/env python3
"""Quick view of Traits API results."""
import pandas as pd

df = pd.read_csv('data/raw/player/footywire_2026_with_traits.csv')

# Convert to numeric
df['Overall_Rating'] = pd.to_numeric(df['Overall_Rating'], errors='coerce')

print("=== TRAITS API RESULTS ===\n")
print(f"Total players: {len(df)}")
print(f"With Traits data: {df['Overall_Rating'].notna().sum()} ({df['Overall_Rating'].notna().mean()*100:.1f}%)")

print("\n=== Top 15 Overall Rated Players ===")
top = df[df['Overall_Rating'].notna()].nlargest(15, 'Overall_Rating')[['Player', 'Team', 'Overall_Rating', 'Position_API']]
print(top.to_string(index=False))

print("\n=== Rating Distribution ===")
print(df['Overall_Rating'].describe())

print("\n=== Traits Coverage by Team ===")
team_cov = df.groupby('Team').agg(
    total=('Player', 'count'),
    with_traits=('Overall_Rating', lambda x: x.notna().sum())
)
team_cov['coverage'] = (team_cov['with_traits'] / team_cov['total'] * 100).round(1)
print(team_cov.sort_values('coverage', ascending=False).to_string())

# Key players check
print("\n=== Key Players ===")
key = ['Patrick Cripps', 'Marcus Bontempelli', 'Nick Daicos', 'Harley Reid', 'Clayton Oliver']
for name in key:
    row = df[df.Player == name]
    if not row.empty:
        r = row.iloc[0]
        rating = r.Overall_Rating if pd.notna(r.Overall_Rating) else 'N/A'
        print(f"  {name:<22} | {r.Team:<18} | Rating: {rating}")
