#!/usr/bin/env python3
"""
Run Traits API against Footywire player DOB data.

Accepts --season flag (defaults to CURRENT_SEASON from config).

This script:
1. Loads DOBs from the Footywire season scrape
2. Updates the DOB cache
3. Queries the Traits API for all players
4. Saves enhanced data back to the season dataset
"""
import argparse
import pandas as pd
import json
import time
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent))
from config.constants import CURRENT_SEASON
from utils.safe_io import safe_csv_write

# Module-level season, overridden by --season arg in main()
SEASON = CURRENT_SEASON

# Import from traits_api module
from traits_api import (
    query_traits_api,
    parse_traits_response,
    load_dob_cache,
    save_dob_cache,
    load_traits_cache,
    save_traits_cache
)


def load_footywire_dobs():
    """Load DOBs from the Footywire scrape."""
    path = Path(f"data/raw/player/footywire_{SEASON}_complete.csv")
    if not path.exists():
        print(f"Error: {path} not found")
        return {}
    
    df = pd.read_csv(path)
    dob_dict = {}
    
    for _, row in df.iterrows():
        player = row['Player']
        dob = row['DOB']
        if pd.notna(player) and pd.notna(dob):
            dob_dict[player] = dob
    
    return dob_dict


def update_dob_cache_from_footywire():
    """Update the DOB cache with Footywire data."""
    print("Loading existing DOB cache...")
    dob_cache = load_dob_cache()
    original_count = len(dob_cache)
    
    print("Loading Footywire DOBs...")
    footywire_dobs = load_footywire_dobs()
    print(f"  Found {len(footywire_dobs)} players with DOBs")
    
    # Update cache with new DOBs (Footywire is authoritative for current lists)
    new_count = 0
    updated_count = 0
    
    for player, dob in footywire_dobs.items():
        if player not in dob_cache:
            dob_cache[player] = dob
            new_count += 1
        elif dob_cache[player] != dob:
            # Update if different (Footywire is more recent)
            dob_cache[player] = dob
            updated_count += 1
    
    save_dob_cache(dob_cache)
    print(f"  DOB cache updated: {new_count} new, {updated_count} updated")
    print(f"  Total DOBs in cache: {len(dob_cache)}")
    
    return dob_cache


def run_traits_api_for_season():
    """Query Traits API for all players in the target season."""
    print("\n" + "=" * 60)
    print(f"Running Traits API for {SEASON} Players")
    print("=" * 60 + "\n")
    
    # Load player data
    df = pd.read_csv(f"data/raw/player/footywire_{SEASON}_complete.csv")
    print(f"Loaded {len(df)} players from {SEASON} dataset")
    
    # Load caches
    dob_cache = load_dob_cache()
    traits_cache = load_traits_cache()
    
    # Stats
    cached_count = 0
    api_success = 0
    api_failed = 0
    no_dob = 0
    api_calls = 0
    
    results = {}
    
    print("\nQuerying Traits API...")
    total = len(df)
    last_save = 0  # Track when we last saved cache
    
    for idx, row in df.iterrows():
        player = row['Player']
        dob = row['DOB'] if pd.notna(row.get('DOB')) else dob_cache.get(player)
        
        # Progress indicator
        if (idx + 1) % 50 == 0 or idx == 0:
            print(f"  Progress: {idx + 1}/{total} ({(idx+1)/total*100:.1f}%)")
        
        # Check traits cache first — but re-query if cached data is from a previous season
        # NOTE: Within the same season we ALWAYS re-query because Traits Insights
        # ratings update week-to-week.  The cache only avoids re-querying across
        # seasons (where old season data never changes).
        if player in traits_cache.get('players', {}):
            cached = traits_cache['players'][player]
            cached_season = str(cached.get('Season_API', ''))
            if str(SEASON) not in cached_season:
                # Different season entirely — cached data is still valid for that old season
                # but we need fresh data for the current season, so fall through
                pass
            # Same season — fall through to re-query with fresh API data

        
        # Query API (DOB used to construct data_provider_id, not sent directly)
        try:
            response = query_traits_api(player, dob)
        except Exception as e:
            print(f"  API exception for {player}: {e}")
            api_failed += 1
            continue
        api_calls += 1
        
        if response:
            parsed = parse_traits_response(response)
            if parsed:
                results[player] = parsed
                traits_cache.setdefault('players', {})[player] = parsed
                api_success += 1
            else:
                api_failed += 1
        else:
            api_failed += 1
        
        # Rate limiting - be nice to the API
        if api_calls % 10 == 0:
            time.sleep(1)
        elif api_calls % 3 == 0:
            time.sleep(0.3)
        
        # Incremental cache save every 25 API calls to prevent data loss on timeout
        if api_calls - last_save >= 25:
            traits_cache['timestamp'] = datetime.now().isoformat()
            save_traits_cache(traits_cache)
            last_save = api_calls
            print(f"  💾  Cache saved ({api_success} successes so far)")
    
    # Save updated cache
    traits_cache['timestamp'] = datetime.now().isoformat()
    save_traits_cache(traits_cache)
    
    print(f"\n{'=' * 60}")
    print("API Query Results:")
    print(f"  From cache: {cached_count}")
    print(f"  API success: {api_success}")
    print(f"  API failed/not found: {api_failed}")
    print(f"  No DOB: {no_dob}")
    print(f"  Total with traits: {len(results)}")
    print(f"  Coverage: {len(results)/len(df)*100:.1f}%")
    
    return results


def enhance_dataset_with_traits(traits_results):
    """Add Traits API data to the season dataset."""
    print("\n" + "=" * 60)
    print(f"Enhancing {SEASON} Dataset with Traits Data")
    print("=" * 60 + "\n")
    
    # Load base data
    df = pd.read_csv(f"data/raw/player/footywire_{SEASON}_complete.csv")
    
    # Key traits columns to add
    trait_columns = [
        'Overall_Rating',
        'data_provider_id',
        'Team_API',
        'Season_API',
        'Position_API',
        # Pillar ratings
        'Ball Winning_Rating',
        'Ball Use_Rating',
        'Aerial_Rating',
        'Defence_Rating',
        # Individual trait ratings
        'Athleticism_Rating',
        'Kicking_Rating', 
        'Marking_Rating',
        'Handballing_Rating',
        'Tackling & Pressure_Rating',
        'Hit-Ups & Groundball_Rating',
        'Ruck_Rating'
    ]
    
    # Initialize columns
    for col in trait_columns:
        df[col] = None
    
    # Apply traits data
    matched = 0
    for idx, row in df.iterrows():
        player = row['Player']
        if player in traits_results:
            traits = traits_results[player]
            for col in trait_columns:
                if col in traits:
                    df.at[idx, col] = traits[col]
            matched += 1
    
    print(f"Matched traits for {matched}/{len(df)} players ({matched/len(df)*100:.1f}%)")
    
    # Save enhanced dataset (atomic write with backup)
    output_path = Path(f"data/raw/player/footywire_{SEASON}_with_traits.csv")
    safe_csv_write(df, output_path)
    print(f"\nSaved to: {output_path}")
    
    # Show sample
    print("\nSample of players with traits:")
    sample_cols = ['Player', 'Team', 'Overall_Rating', 'Athleticism_Rating', 'Kicking_Rating']
    sample = df[df['Overall_Rating'].notna()][sample_cols].head(10)
    print(sample.to_string())
    
    # Show top rated players
    print("\nTop 10 Overall Rated Players:")
    df['Overall_Rating'] = pd.to_numeric(df['Overall_Rating'], errors='coerce')
    top_rated = df[df['Overall_Rating'].notna()].nlargest(10, 'Overall_Rating')[sample_cols]
    print(top_rated.to_string(index=False))
    
    return df


def main():
    global SEASON

    parser = argparse.ArgumentParser(description="Run Traits API for AFL player data")
    parser.add_argument("--season", type=int, default=CURRENT_SEASON,
                        help=f"Season year (default: {CURRENT_SEASON})")
    args = parser.parse_args()
    SEASON = args.season

    print("=" * 60)
    print(f"Traits API Integration for {SEASON} Footywire Data")
    print("=" * 60)
    print()

    # Step 1: Update DOB cache with Footywire data
    try:
        update_dob_cache_from_footywire()
    except Exception as e:
        print(f"\n⚠️  DOB cache update failed: {e}")

    # Step 2: Run Traits API for all players
    try:
        traits_results = run_traits_api_for_season()
    except Exception as e:
        print(f"\n⚠️  Traits API query failed: {e}")
        traits_results = {}

    # Step 3: Enhance the dataset
    if traits_results:
        try:
            enhance_dataset_with_traits(traits_results)
        except Exception as e:
            print(f"\n⚠️  Dataset enhancement failed: {e}")
    else:
        print("\nNo traits data retrieved!")

    # Step 4: Snapshot traits for the current round (for Trait Rating Matrix)
    try:
        snapshot_traits_to_history()
    except Exception as e:
        print(f"\n⚠️  Traits snapshot failed: {e}")


# ---------------------------------------------------------------------------
# Snapshot stability thresholds
# ---------------------------------------------------------------------------
# After a round, Traits Insights ratings take 1-2 days to settle.  We save
# each API fetch as a "pending" snapshot and only promote it to the
# official traits_history once two consecutive fetches are consistent.
#
# Schedule context:  traits_api runs Sun / Mon / Tue (STEP_DAY_RESTRICTIONS).
# Typical flow for Round N:
#   Sunday  — first fetch after the round → saved as pending (no prior to compare)
#   Monday  — second fetch → compared against Sunday's pending
#   Tuesday — third fetch  → compared against Monday's; if stable → promoted
#
# A snapshot is considered "stable" when:
#   1. The mean |Δ Overall_Rating| across all matched players is below
#      STABILITY_MEAN_THRESHOLD, AND
#   2. The max |Δ Overall_Rating| for any single player is below
#      STABILITY_MAX_THRESHOLD, AND
#   3. At least STABILITY_MIN_PLAYERS players are present.
STABILITY_MEAN_THRESHOLD = 0.03   # avg movement ≤ 0.03 rating points
STABILITY_MAX_THRESHOLD  = 0.20   # no single player moved > 0.20
STABILITY_MIN_PLAYERS    = 300    # minimum players with a rating


def snapshot_traits_to_history():
    """Validate trait data stability before committing a per-round snapshot.

    On each run:
      1. Build a fresh snapshot from the just-updated traits file.
      2. Compare it to the pending snapshot from the previous run (if any).
      3. If the data has stabilised → promote to traits_history (final).
         If not → save as the new pending and wait for the next run.
    """
    match_ratings_path = Path(f"data/raw/player/match_ratings_{SEASON}.csv")
    traits_path = Path(f"data/raw/traits/traits_{SEASON}.csv")

    if not match_ratings_path.exists() or not traits_path.exists():
        print("\nSnapshot: Missing match_ratings or traits file, skipping")
        return

    mr = pd.read_csv(match_ratings_path)
    if "Round" not in mr.columns or mr.empty:
        print("\nSnapshot: No round data in match_ratings, skipping")
        return
    current_round = int(mr["Round"].max())
    if current_round <= 0:
        return

    traits = pd.read_csv(traits_path)
    if "Overall_Rating" not in traits.columns:
        print("\nSnapshot: No Overall_Rating in traits file, skipping")
        return

    # Build the candidate snapshot from the fresh fetch
    # Include pillar ratings if available in the traits CSV
    snapshot_cols = ["Player", "Team", "Overall_Rating"]
    pillar_cols = ["Ball Winning_Rating", "Ball Use_Rating", "Aerial_Rating", "Defence_Rating"]
    available_pillars = [c for c in pillar_cols if c in traits.columns]
    snapshot_cols.extend(available_pillars)

    candidate = traits[snapshot_cols].copy()
    candidate["Overall_Rating"] = pd.to_numeric(candidate["Overall_Rating"], errors="coerce")
    for pc in available_pillars:
        candidate[pc] = pd.to_numeric(candidate[pc], errors="coerce")
    candidate = candidate[candidate["Overall_Rating"].notna()].reset_index(drop=True)

    if len(candidate) < STABILITY_MIN_PLAYERS:
        print(f"\nSnapshot: Only {len(candidate)} players with ratings "
              f"(need {STABILITY_MIN_PLAYERS}), skipping")
        return

    # ---- Check for an existing pending snapshot ----------------------------
    pending_dir = Path(f"data/raw/traits/pending")
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending_path = pending_dir / f"traits_pending_{SEASON}_R{current_round}.csv"

    history_path = Path(f"data/raw/traits/traits_history_{SEASON}.csv")

    # Check if this round is already finalised in history
    if history_path.exists():
        history = pd.read_csv(history_path)
        finalised_rounds = set(history["Round"].unique()) if not history.empty else set()
    else:
        history = pd.DataFrame(columns=["Player", "Team", "Round", "Overall_Rating",
                                          "Ball Winning_Rating", "Ball Use_Rating",
                                          "Aerial_Rating", "Defence_Rating"])
        finalised_rounds = set()

    if current_round in finalised_rounds:
        # Already have a final snapshot for this round — update it silently
        # (handles re-runs after promotion)
        _write_final_snapshot(candidate, current_round, history, history_path)
        print(f"\nSnapshot: R{current_round} already finalised — updated with latest values")
        return

    if not pending_path.exists():
        # First fetch for this round — save as pending, nothing to compare yet
        safe_csv_write(candidate, pending_path)
        print(f"\nSnapshot: R{current_round} — first fetch saved as pending "
              f"({len(candidate)} players). Will validate on next run.")
        return

    # ---- Compare candidate vs prior pending --------------------------------
    prior = pd.read_csv(pending_path)
    prior["Overall_Rating"] = pd.to_numeric(prior["Overall_Rating"], errors="coerce")

    merged = candidate.merge(prior, on=["Player", "Team"], suffixes=("_new", "_old"),
                             how="inner")
    merged = merged[merged["Overall_Rating_old"].notna() & merged["Overall_Rating_new"].notna()]

    if merged.empty:
        safe_csv_write(candidate, pending_path)
        print(f"\nSnapshot: R{current_round} — no overlap with prior pending, "
              f"saved fresh pending ({len(candidate)} players)")
        return

    merged["_delta"] = (merged["Overall_Rating_new"] - merged["Overall_Rating_old"]).abs()
    mean_delta = merged["_delta"].mean()
    max_delta  = merged["_delta"].max()
    pct_moved  = (merged["_delta"] > 0.001).mean() * 100
    n_matched  = len(merged)

    print(f"\nSnapshot validation for R{current_round}:")
    print(f"  Players compared : {n_matched}")
    print(f"  Mean |Δ rating|  : {mean_delta:.4f}  (threshold: {STABILITY_MEAN_THRESHOLD})")
    print(f"  Max  |Δ rating|  : {max_delta:.4f}  (threshold: {STABILITY_MAX_THRESHOLD})")
    print(f"  % players moved  : {pct_moved:.1f}%")

    is_stable = (mean_delta <= STABILITY_MEAN_THRESHOLD
                 and max_delta <= STABILITY_MAX_THRESHOLD)

    if is_stable:
        # Data has settled — promote to final history
        _write_final_snapshot(candidate, current_round, history, history_path)
        # Clean up pending file
        pending_path.unlink(missing_ok=True)
        print(f"  ✅ STABLE — promoted R{current_round} snapshot to traits_history "
              f"({len(candidate)} players)")
    else:
        # Still moving — overwrite pending with latest and wait
        safe_csv_write(candidate, pending_path)
        # Show the biggest movers for debugging
        top_movers = merged.nlargest(5, "_delta")[["Player", "Team",
                                                    "Overall_Rating_old",
                                                    "Overall_Rating_new", "_delta"]]
        print(f"  ⏳ NOT STABLE — saved as pending. Top movers:")
        for _, row in top_movers.iterrows():
            print(f"     {row['Player']:30s}  "
                  f"{row['Overall_Rating_old']:.2f} → {row['Overall_Rating_new']:.2f}  "
                  f"(Δ {row['_delta']:.2f})")


def _write_final_snapshot(candidate, current_round, history, history_path):
    """Write a validated snapshot into traits_history."""
    history = history[history["Round"] != current_round]
    snapshot = candidate.copy()
    snapshot["Round"] = current_round
    history = pd.concat([history, snapshot], ignore_index=True)
    safe_csv_write(history, history_path)


if __name__ == "__main__":
    main()
