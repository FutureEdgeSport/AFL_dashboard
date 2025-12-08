#!/usr/bin/env python3
"""
Test which team codes work for player photos
"""

import requests

# Test player provider IDs (one per team from their websites)
TEST_PLAYERS = {
    "Adelaide": ("014", "992242"),  # Jordan Dawson - KNOWN TO WORK
    "Brisbane": ("020", "293535"),  # Lachie Neale
    "Carlton": ("030", "993770"),   # Patrick Cripps
    "Collingwood": ("040", "996075"),  # Scott Pendlebury  
    "Essendon": ("050", "296475"),  # Zach Merrett
    "Fremantle": ("060", "280502"),  # Nat Fyfe
    "Geelong": ("070", "295131"),  # Patrick Dangerfield
    "Gold Coast": ("100", "280576"),  # Touk Miller
    "GWS": ("110", "993891"),  # Toby Greene
    "Hawthorn": ("080", "280480"),  # James Sicily
    "Melbourne": ("090", "295504"),  # Max Gawn
    "North Melbourne": ("150", "280509"),  # Luke McDonald
    "Port Adelaide": ("160", "294951"),  # Travis Boak
    "Richmond": ("120", "280564"),  # Dion Prestia
    "St Kilda": ("130", "295502"),  # Jack Steele
    "Sydney": ("140", "296297"),  # Callum Mills
    "West Coast": ("170", "297473"),  # Elliot Yeo
    "Western Bulldogs": ("180", "280566"),  # Marcus Bontempelli
}

print("Testing player photo URLs...")
print("="*70)

for team, (code, provider_id) in TEST_PLAYERS.items():
    url = f"https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Players/ChampIDImages/AFL/2026{code}/{provider_id}.png"
    
    try:
        response = requests.head(url, timeout=5)
        status = "✓" if response.status_code == 200 else "✗"
        print(f"{status} {team:20s} code={code} provider={provider_id} HTTP {response.status_code}")
    except Exception as e:
        print(f"✗ {team:20s} code={code} ERROR: {str(e)}")

print("="*70)
