"""
Centralized Player Name Resolution
====================================
Single source of truth for matching player names across all data sources.

Problem this solves:
    - Different sources use different name formats:
      * Formal: "Zachary Merrett", "Lachlan Ash", "Timothy English"
      * Informal: "Zach Merrett", "Lachie Ash", "Tim English"
      * Abbreviated: "A. Cadman", "C. Mills", "Ch. Warner"
    - Without centralised resolution, every merge/join/lookup must
      independently handle these variants (and often doesn't).

Usage:
    from config.player_names import get_resolver

    resolver = get_resolver()

    # Single name
    canonical = resolver.resolve("Zach Merrett", team="Essendon")
    # → "Zachary Merrett" (or whatever the canonical form is)

    # Whole DataFrame column (fast, vectorized)
    df["Player"] = resolver.resolve_df(df, "Player", "Team")

Design:
    - Canonical names come from player_summary.csv (primary) and the
      current-season CSV (secondary, for rookies/draftees not in summary).
    - Resolution order: exact → lowercase → nickname-expanded → surname+team
    - Thread-safe singleton via module-level caching.
    - Rebuilt automatically when source data changes (via mtime check).
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from config.constants import (
    PLAYER_NICKNAME_MAP,
    TEAM_CODE_TO_NAME,
    get_nickname_variants,
    normalize_team_name,
)

# ============================================================================
# Module-level cache
# ============================================================================
_resolver_instance: Optional["PlayerNameResolver"] = None
_resolver_mtime: float = 0.0

BASE_DIR = Path(__file__).resolve().parent.parent


def get_resolver(force_rebuild: bool = False) -> "PlayerNameResolver":
    """Return the singleton PlayerNameResolver, rebuilding if source files changed."""
    global _resolver_instance, _resolver_mtime

    summary_path = BASE_DIR / "data" / "computed" / "player_summary.csv"
    latest_mtime = summary_path.stat().st_mtime if summary_path.exists() else 0.0

    if _resolver_instance is None or force_rebuild or latest_mtime > _resolver_mtime:
        _resolver_instance = PlayerNameResolver()
        _resolver_mtime = latest_mtime

    return _resolver_instance


# ============================================================================
# Helpers
# ============================================================================

def _normalize(name: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return " ".join(str(name).strip().lower().split())


def _extract_surname(name: str) -> str:
    """Last whitespace-delimited token, lowercased."""
    parts = str(name).strip().split()
    return parts[-1].lower() if parts else ""


def _parse_initial_surname(name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse "A. Cadman" or "Ch. Warner" into (initials_upper, surname).
    Returns (None, None) if the name doesn't match the pattern.
    """
    m = re.match(r"^([A-Za-z]{1,3})\.?\s+(.+)$", str(name).strip())
    if m and len(m.group(1)) <= 3:
        # Only treat as abbreviated if the first part looks like initials
        first_part = m.group(1)
        if len(first_part) <= 2 or (len(first_part) == 3 and first_part[0].isupper()):
            return first_part.upper(), m.group(2).strip()
    return None, None


# ============================================================================
# PlayerNameResolver
# ============================================================================

class PlayerNameResolver:
    """
    Resolve any player name variant to its canonical form.

    Resolution cascade:
        1. Exact match (case-sensitive)
        2. Case-insensitive match
        3. Nickname-expanded match (Zachary↔Zach, Lachlan↔Lachie, etc.)
        4. Initial+surname → full name (A. Cadman → Aaron Cadman)
        5. Surname + team fallback (unique surname within team)

    The canonical name set is built from:
        - data/computed/player_summary.csv (primary — ~668 players)
        - data/raw/player/squads_{CURRENT_SEASON}.csv (secondary)
        - data/raw/traits/traits_{CURRENT_SEASON}.csv (tertiary)
    """

    def __init__(self) -> None:
        # Canonical name → team (the "truth")
        self._canonical: Dict[str, str] = {}

        # Lookup indexes
        self._exact: Dict[str, str] = {}         # name → canonical
        self._lower: Dict[str, str] = {}          # lower(name) → canonical
        self._surname_team: Dict[Tuple[str, str], str] = {}  # (surname_lower, team) → canonical

        self._build()

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Load canonical names from all known sources and build indexes.
        
        Two-phase approach:
          Phase 1: Load primary sources (summary, photo guide) as canonical.
                   Build indexes including nickname variants.
          Phase 2: Load secondary sources (squads, traits CSVs). For each name,
                   try to resolve it against phase-1 indexes. If it resolves,
                   register a mapping. If not, add as new canonical name.
        """
        # ------ Phase 1: primary sources → canonical names ------
        primary_pairs: List[Tuple[str, str]] = []

        # 1a. player_summary.csv (most authoritative)
        summary = BASE_DIR / "data" / "computed" / "player_summary.csv"
        if summary.exists():
            try:
                df = pd.read_csv(summary, usecols=["Player", "Team"])
                for _, row in df.iterrows():
                    name = str(row["Player"]).strip()
                    team = normalize_team_name(str(row.get("Team", "")).strip())
                    if name and name != "nan":
                        primary_pairs.append((name, team))
            except Exception:
                pass

        # 1b. Photo guide (carefully curated names)
        guide = BASE_DIR / "player_photo_guide.csv"
        if guide.exists():
            try:
                df = pd.read_csv(guide, usecols=["Player", "Team"])
                for _, row in df.iterrows():
                    name = str(row["Player"]).strip()
                    team = normalize_team_name(str(row.get("Team", "")).strip())
                    if name and name != "nan":
                        primary_pairs.append((name, team))
            except Exception:
                pass

        # De-dup primary: first occurrence wins
        seen_primary: Set[str] = set()
        for name, team in primary_pairs:
            if name not in seen_primary:
                self._canonical[name] = team
                seen_primary.add(name)

        # Build initial indexes from primary canonical names
        self._build_indexes()

        # ------ Phase 2: secondary sources → resolve or add ------
        from config.constants import CURRENT_SEASON

        secondary_files = [
            BASE_DIR / "data" / "raw" / "player" / f"squads_{CURRENT_SEASON}.csv",
            BASE_DIR / "data" / "raw" / "traits" / f"traits_{CURRENT_SEASON}.csv",
        ]

        for fpath in secondary_files:
            if not fpath.exists():
                continue
            try:
                df = pd.read_csv(fpath)
                df.columns = [str(c).strip() for c in df.columns]
                name_col = "Player" if "Player" in df.columns else None
                team_col = "Team" if "Team" in df.columns else None
                if not name_col:
                    continue
                for _, row in df.iterrows():
                    name = str(row[name_col]).strip()
                    raw_team = str(row.get(team_col, "")).strip() if team_col else ""
                    team = normalize_team_name(raw_team)
                    if not name or name == "nan":
                        continue

                    # Try to resolve against existing indexes
                    resolved = self._resolve_internal(name, team)
                    if resolved != name:
                        # Already resolvable — just ensure the mapping exists
                        if name not in self._exact:
                            self._exact[name] = resolved
                        low = _normalize(name)
                        if low not in self._lower:
                            self._lower[low] = resolved
                    elif name not in self._canonical:
                        # Genuinely new player — add as canonical
                        self._canonical[name] = team
                        self._exact[name] = name
                        low = _normalize(name)
                        if low not in self._lower:
                            self._lower[low] = name
            except Exception:
                pass

        # Rebuild indexes to include new canonical names from secondary
        self._build_indexes()

    def _build_indexes(self) -> None:
        """Build/rebuild all lookup indexes from the current canonical set."""
        self._exact.clear()
        self._lower.clear()
        self._surname_team.clear()

        # Helper: two canonical names are nickname-equivalent when they
        # share surname+team and their first names are nickname variants.
        # Used so ("Zach Merrett", "Zachary Merrett") don't block each other
        # from uniqueness-based shortcuts.
        def _same_player(a: str, b: str) -> bool:
            if a == b:
                return True
            pa, pb = a.split(), b.split()
            if len(pa) < 2 or len(pb) < 2:
                return False
            if " ".join(pa[1:]).lower() != " ".join(pb[1:]).lower():
                return False
            if self._canonical.get(a, "") != self._canonical.get(b, ""):
                return False
            va = {v.lower() for v in get_nickname_variants(pa[0])} | {pa[0].lower()}
            vb = {v.lower() for v in get_nickname_variants(pb[0])} | {pb[0].lower()}
            return bool(va & vb) or pb[0].lower() in va or pa[0].lower() in vb

        # Exact + case-insensitive
        for canon in self._canonical:
            self._exact[canon] = canon
            low = _normalize(canon)
            if low not in self._lower:
                self._lower[low] = canon

        # Nickname variants
        for canon in list(self._canonical.keys()):
            parts = canon.split()
            if len(parts) >= 2:
                first = parts[0]
                rest = " ".join(parts[1:])
                for variant_first in get_nickname_variants(first):
                    variant = f"{variant_first.capitalize()} {rest}"
                    if variant not in self._exact:
                        self._exact[variant] = canon
                    low = _normalize(variant)
                    if low not in self._lower:
                        self._lower[low] = canon

        # Initial+surname — only register globally if unique.
        # If multiple canonical players share the same initial+surname, we
        # skip the global shortcut so resolution must fall through to the
        # team-aware lookup (_initial_surname_team below) and can't silently
        # misroute (e.g. "B. Smith" → whichever B. Smith was added first).
        initial_surname_groups: Dict[str, List[str]] = defaultdict(list)
        for canon in self._canonical:
            parts = canon.split()
            if len(parts) >= 2 and len(parts[0]) > 1:
                initial = parts[0][0].upper()
                surname = " ".join(parts[1:])
                initial_surname_groups[f"{initial}. {surname}"].append(canon)
        for abbrev, names in initial_surname_groups.items():
            # Collapse nickname-equivalent duplicates (Zach/Zachary Merrett)
            unique: List[str] = []
            for n in names:
                if not any(_same_player(n, u) for u in unique):
                    unique.append(n)
            if len(unique) == 1:
                canon = unique[0]
                if abbrev not in self._exact:
                    self._exact[abbrev] = canon
                low = _normalize(abbrev)
                if low not in self._lower:
                    self._lower[low] = canon

        # Initial + surname + team (used for disambiguation when the
        # global shortcut above is ambiguous).
        self._initial_surname_team: Dict[Tuple[str, str, str], str] = {}
        ist_groups: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)
        for canon, team in self._canonical.items():
            parts = canon.split()
            if len(parts) >= 2 and len(parts[0]) > 1 and team:
                initial = parts[0][0].upper()
                surname = _extract_surname(canon)
                ist_groups[(initial, surname, team)].append(canon)
        for key, names in ist_groups.items():
            unique: List[str] = []
            for n in names:
                if not any(_same_player(n, u) for u in unique):
                    unique.append(n)
            if len(unique) == 1:
                self._initial_surname_team[key] = unique[0]

        # Surname + team (only unique surname per team)
        surname_team_groups: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for canon, team in self._canonical.items():
            surname = _extract_surname(canon)
            if surname and team:
                surname_team_groups[(surname, team)].append(canon)
        for key, names in surname_team_groups.items():
            unique: List[str] = []
            for n in names:
                if not any(_same_player(n, u) for u in unique):
                    unique.append(n)
            if len(unique) == 1:
                self._surname_team[key] = unique[0]
    def _resolve_internal(self, name: str, team: str = "") -> str:
        """Internal resolve used during index building (avoids recursion)."""
        if name in self._exact:
            return self._exact[name]
        low = _normalize(name)
        if low in self._lower:
            return self._lower[low]
        # Nickname expansion
        parts = name.split()
        if len(parts) >= 2:
            first = parts[0]
            rest = " ".join(parts[1:])
            for variant_first in get_nickname_variants(first):
                variant = f"{variant_first.capitalize()} {rest}"
                if variant in self._exact:
                    return self._exact[variant]
                vlow = _normalize(variant)
                if vlow in self._lower:
                    return self._lower[vlow]
        # Initial+surname — global shortcut (only populated when globally unique)
        initials, surname_part = _parse_initial_surname(name)
        if initials and surname_part:
            abbrev = f"{initials[0]}. {surname_part}"
            if abbrev in self._exact:
                return self._exact[abbrev]
            # Team-scoped initial+surname for ambiguous cases
            if team:
                matched = self._initial_surname_team.get(
                    (initials[0].upper(), surname_part.lower(), team)
                )
                if matched:
                    return matched
        # Surname+team (requires initial match if input had an initial, to
        # prevent "B. Crouch" → "Matt Crouch" style misroutes)
        if team:
            surname_only = _extract_surname(name)
            if surname_only:
                matched = self._surname_team.get((surname_only, team))
                if matched and (not initials or matched.split()[0][0].upper() == initials[0].upper()):
                    return matched
        return name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, name: str, team: Optional[str] = None) -> str:
        """
        Resolve a player name to its canonical form.

        Args:
            name: Any variant of the player's name.
            team: Optional team name/code for disambiguation.

        Returns:
            The canonical name if matched, otherwise the original name
            (stripped).
        """
        if not isinstance(name, str) or not name.strip():
            return str(name).strip() if name else ""

        name = name.strip()
        norm_team = normalize_team_name(str(team).strip()) if team else ""

        # 1. Exact
        if name in self._exact:
            return self._exact[name]

        # 2. Case-insensitive
        low = _normalize(name)
        if low in self._lower:
            return self._lower[low]

        # 3. Nickname expansion (not pre-registered — handles novel combos)
        parts = name.split()
        if len(parts) >= 2:
            first = parts[0]
            rest = " ".join(parts[1:])
            for variant_first in get_nickname_variants(first):
                variant = f"{variant_first.capitalize()} {rest}"
                if variant in self._exact:
                    return self._exact[variant]
                vlow = _normalize(variant)
                if vlow in self._lower:
                    return self._lower[vlow]

        # 4. Initial+surname match (A. Cadman → Aaron Cadman)
        initials, surname_part = _parse_initial_surname(name)
        if initials and surname_part:
            abbrev = f"{initials[0]}. {surname_part}"
            if abbrev in self._exact:
                return self._exact[abbrev]
            # 4b. Team-scoped initial+surname (for non-unique initials)
            if norm_team:
                matched = self._initial_surname_team.get(
                    (initials[0].upper(), surname_part.lower(), norm_team)
                )
                if matched:
                    return matched

        # 5. Surname + team (unique within team).  If the input carried an
        # initial (e.g. "B. Crouch"), require it to match the canonical's
        # first initial, so a single team's Matt Crouch doesn't swallow
        # "B. Crouch" (Brad).
        if norm_team:
            surname_only = _extract_surname(name)
            if surname_only:
                matched = self._surname_team.get((surname_only, norm_team))
                if matched and (
                    not initials or matched.split()[0][0].upper() == initials[0].upper()
                ):
                    return matched

        return name

    def resolve_df(
        self,
        df: pd.DataFrame,
        name_col: str = "Player",
        team_col: Optional[str] = "Team",
    ) -> pd.Series:
        """
        Resolve an entire DataFrame column of player names.

        Args:
            df: Source DataFrame
            name_col: Column containing player names
            team_col: Column containing team names (for disambiguation).
                      Pass None to skip team-aware matching.

        Returns:
            pd.Series with resolved canonical names (same index as df).
        """
        if name_col not in df.columns:
            return df.get(name_col, pd.Series(dtype=str))

        names = df[name_col].astype(str).str.strip()
        teams = df[team_col].astype(str).str.strip() if (team_col and team_col in df.columns) else pd.Series([""] * len(df), index=df.index)

        return pd.Series(
            [self.resolve(n, t) for n, t in zip(names, teams)],
            index=df.index,
        )

    @property
    def canonical_names(self) -> Dict[str, str]:
        """Return a copy of {canonical_name: team} for inspection."""
        return dict(self._canonical)

    def stats(self) -> Dict[str, int]:
        """Return index sizes for diagnostics."""
        return {
            "canonical_players": len(self._canonical),
            "exact_keys": len(self._exact),
            "lower_keys": len(self._lower),
            "surname_team_keys": len(self._surname_team),
        }
