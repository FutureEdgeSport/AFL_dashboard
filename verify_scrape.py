#!/usr/bin/env python3
"""Quick verification of scraped data."""
import pandas as pd

df = pd.read_csv('data/raw/player/footywire_2026_complete.csv')

print('=== Key Players ===')
key_players = ['Patrick Cripps', 'Marcus Bontempelli', 'Nick Daicos', 'Harley Reid', 'Clayton Oliver']
for name in key_players:
    row = df[df.Player == name]
    if not row.empty:
        r = row.iloc[0]
        exp = int(r.Contract_Expiry) if pd.notna(r.Contract_Expiry) else 'N/A'
        yr = int(r.Draft_Year) if pd.notna(r.Draft_Year) else 'N/A'
        rd = int(r.Draft_Round) if pd.notna(r.Draft_Round) else '?'
        pk = int(r.Draft_Pick) if pd.notna(r.Draft_Pick) else '?'
        print(f"{r.Player:<22} | {r.Team:<18} | Exp: {exp} | {r.FA_Status:<24} | Draft: {yr} R{rd} P{pk} ({r.Draft_Type})")

print()
print('=== Missing Draft Data (Top 15 by games) ===')
missing = df[df.Draft_Year.isna()].sort_values('Games', ascending=False)[['Team', 'Player', 'Games']].head(15)
print(missing.to_string(index=False))

print()
print('=== Data Coverage Summary ===')
print(f"Total players: {len(df)}")
print(f"Contract Expiry: {df.Contract_Expiry.notna().sum()}/{len(df)} ({df.Contract_Expiry.notna().mean()*100:.1f}%)")
print(f"FA Status: {df.FA_Status.notna().sum()}/{len(df)} ({df.FA_Status.notna().mean()*100:.1f}%)")
print(f"Draft Year: {df.Draft_Year.notna().sum()}/{len(df)} ({df.Draft_Year.notna().mean()*100:.1f}%)")

print()
print('=== FA Status Distribution ===')
print(df.FA_Status.value_counts().to_string())

print()
print('=== Contract Expiry Distribution ===')
print(df.Contract_Expiry.value_counts().sort_index().to_string())
