#!/usr/bin/env python3
"""Quick test of load_traits function"""
import sys
import pandas as pd

# Mock streamlit
class MockST:
    def cache_data(self, **kwargs):
        def decorator(f):
            return f
        return decorator
    def cache_resource(self, **kwargs):
        return self.cache_data(**kwargs)
    def set_page_config(self, **kwargs): pass
    def markdown(self, *args, **kwargs): pass
    def error(self, msg): print(f"ERROR: {msg}")
    def warning(self, msg): print(f"WARNING: {msg}")
    
sys.modules['streamlit'] = MockST()
sys.modules['streamlit.components'] = type(sys)('streamlit.components')
sys.modules['streamlit.components.v1'] = type(sys)('streamlit.components.v1')

# Now we can import
from traits_api import load_traits_cache

TRAITS_API_AVAILABLE = True

def _load_traits_api_cache():
    if not TRAITS_API_AVAILABLE:
        return {}
    try:
        cache = load_traits_cache()
        return cache.get('players', {})
    except Exception:
        return {}

def _enhance_traits_with_api(df, api_cache):
    if not api_cache:
        return df
    
    API_TO_EXCEL = {
        'Overall_Rating': 'Rating',
        'Ball Winning_Rating': 'Ball Winning',
        'Ball Use_Rating': 'Ball Use',
        'Aerial_Rating': 'Aerial',
        'Defence_Rating': 'Defence',
        'Ball Winning_Stoppage': 'Stoppage',
        'Ball Winning_Contest': 'Contest',
        'Ball Winning_Power': 'Power',
        'Ball Winning_Receives': 'Receives',
        'Ball Use_Handballing': 'Handballing',
        'Ball Use_Kicking': 'Kicking',
        'Ball Use_Goal Kicking': 'Goal Kicking',
        'Ball Use_Connecting': 'Connecting',
        'Aerial_Marking': 'Marking',
        'Aerial_Contested': 'Contested',
        'Aerial_Moks': 'Moks',
        'Aerial_Ruck': 'Ruck',
        'Defence_Pressure': 'Pressure',
        'Defence_Tackling': 'Tackling',
        'Defence_Intercepting': 'Intercepting',
        'Defence_Neutralise': 'Neutralise',
    }
    
    updated_count = 0
    for idx, row in df.iterrows():
        player_name = row.get('Player_Full') or row.get('Player', '')
        api_data = api_cache.get(player_name)
        if not api_data:
            continue
        for api_col, excel_col in API_TO_EXCEL.items():
            if excel_col in df.columns and api_col in api_data:
                api_val = api_data[api_col]
                if api_val is not None and not pd.isna(api_val):
                    df.at[idx, excel_col] = api_val
        updated_count += 1
    
    print(f"Enhanced {updated_count} players with API data")
    return df

# Test it
print("Loading Excel traits...")
df = pd.read_excel('2025 Traits ENRICHED.xlsx', sheet_name='2025')
df.columns = [str(c).strip() for c in df.columns]
print(f"Excel: {len(df)} players")

# Add Player_Full if missing
if 'Player_Full' not in df.columns:
    df['Player_Full'] = df['Player']

print("\nLoading API cache...")
api_cache = _load_traits_api_cache()
print(f"API cache: {len(api_cache)} players")

print("\nEnhancing with API data...")
df = _enhance_traits_with_api(df, api_cache)

# Check result
print("\nSample results:")
for player in ['Patrick Cripps', 'Marcus Bontempelli', 'Max Gawn']:
    row = df[df['Player_Full'] == player]
    if not row.empty:
        r = row.iloc[0]
        print(f"  {player}: Rating={r['Rating']}, BW={r['Ball Winning']}, BU={r['Ball Use']}")

print("\n✓ Integration test passed!")
