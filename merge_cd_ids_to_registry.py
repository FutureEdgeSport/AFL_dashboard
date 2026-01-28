#!/usr/bin/env python3
"""
Merge Champion Data IDs into Player Registry
=============================================
Adds champion_data_id column to player_registry.xlsx by matching
player names from champion_data_player_ids.xlsx.

Usage:
    python merge_cd_ids_to_registry.py
"""

import pandas as pd
from pathlib import Path
import re

def normalize_name(name):
    """Normalize name for matching."""
    if pd.isna(name):
        return ''
    return re.sub(r'[^\w\s]', '', str(name).lower()).strip()

def main():
    print("="*60)
    print("   MERGE CHAMPION DATA IDs INTO PLAYER REGISTRY")
    print("="*60)
    print()
    
    base_dir = Path(__file__).parent
    
    # Load files
    print("📂 Loading files...")
    registry = pd.read_excel(base_dir / 'player_registry.xlsx')
    cd_ids = pd.read_excel(base_dir / 'champion_data_player_ids.xlsx')
    
    print(f"   Player Registry: {len(registry)} players")
    print(f"   CD IDs file: {len(cd_ids)} players")
    print()
    
    # Create lookup dict from CD IDs file
    # Key: normalized full name -> CD ID
    cd_lookup = {}
    for _, row in cd_ids.iterrows():
        full_name = normalize_name(row.get('full_name', ''))
        cd_id = str(row.get('champion_data_id', ''))
        if full_name and cd_id:
            cd_lookup[full_name] = cd_id
    
    print(f"📊 CD ID lookup created: {len(cd_lookup)} unique names")
    print()
    
    # Match and add CD IDs to registry
    print("🔗 Matching players...")
    
    matched = 0
    unmatched = []
    
    # Add new column
    registry['champion_data_id'] = ''
    
    for idx, row in registry.iterrows():
        # Try canonical name first
        canonical = normalize_name(row.get('full_name_canonical', ''))
        if canonical in cd_lookup:
            registry.at[idx, 'champion_data_id'] = cd_lookup[canonical]
            matched += 1
            continue
        
        # Try raw name
        raw = normalize_name(row.get('full_name_raw', ''))
        if raw in cd_lookup:
            registry.at[idx, 'champion_data_id'] = cd_lookup[raw]
            matched += 1
            continue
        
        # Try name variants if available
        variants = row.get('name_variants', '')
        if pd.notna(variants):
            for variant in str(variants).split(','):
                variant_norm = normalize_name(variant)
                if variant_norm in cd_lookup:
                    registry.at[idx, 'champion_data_id'] = cd_lookup[variant_norm]
                    matched += 1
                    break
            else:
                unmatched.append(row.get('full_name_canonical', row.get('full_name_raw', 'Unknown')))
        else:
            unmatched.append(row.get('full_name_canonical', row.get('full_name_raw', 'Unknown')))
    
    print(f"   ✅ Matched: {matched}")
    print(f"   ❌ Unmatched: {len(unmatched)}")
    print()
    
    # Show some unmatched for review
    if unmatched:
        print("📋 Sample unmatched players (first 20):")
        for name in unmatched[:20]:
            print(f"      - {name}")
        print()
    
    # Reorder columns to put champion_data_id near the front
    cols = list(registry.columns)
    if 'champion_data_id' in cols:
        cols.remove('champion_data_id')
        # Insert after player_uid
        if 'player_uid' in cols:
            uid_idx = cols.index('player_uid')
            cols.insert(uid_idx + 1, 'champion_data_id')
        else:
            cols.insert(0, 'champion_data_id')
    registry = registry[cols]
    
    # Save updated registry
    output_file = base_dir / 'player_registry.xlsx'
    backup_file = base_dir / 'player_registry_backup.xlsx'
    
    # Create backup
    import shutil
    shutil.copy(output_file, backup_file)
    print(f"📦 Backup created: {backup_file.name}")
    
    # Save
    registry.to_excel(output_file, index=False)
    print(f"💾 Saved: {output_file.name}")
    
    # Summary stats
    with_cd = len(registry[registry['champion_data_id'] != ''])
    print()
    print("="*60)
    print("   SUMMARY")
    print("="*60)
    print(f"   Total players in registry: {len(registry)}")
    print(f"   Players with CD ID: {with_cd}")
    print(f"   Players without CD ID: {len(registry) - with_cd}")
    print()
    
    # Show sample
    print("📋 Sample of updated registry:")
    sample = registry[registry['champion_data_id'] != ''][['full_name_canonical', 'champion_data_id', 'teams_seen']].head(10)
    print(sample.to_string())


if __name__ == '__main__':
    main()
