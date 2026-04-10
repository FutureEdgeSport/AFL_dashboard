"""Tests for centralized PlayerNameResolver."""
import pytest
from config.player_names import PlayerNameResolver, get_resolver, _normalize, _extract_surname, _parse_initial_surname


class TestHelpers:
    def test_normalize(self):
        assert _normalize("  Zach  Merrett  ") == "zach merrett"
        assert _normalize("Tom De Koning") == "tom de koning"

    def test_extract_surname(self):
        assert _extract_surname("Zach Merrett") == "merrett"
        assert _extract_surname("Tom De Koning") == "koning"
        assert _extract_surname("A. Cadman") == "cadman"

    def test_parse_initial_surname(self):
        ini, sur = _parse_initial_surname("A. Cadman")
        assert ini == "A"
        assert sur == "Cadman"

        ini, sur = _parse_initial_surname("Ch. Warner")
        assert ini == "CH"
        assert sur == "Warner"

        ini, sur = _parse_initial_surname("Zachary Merrett")
        assert ini is None  # Not an abbreviated name


class TestResolver:
    @pytest.fixture(scope="class")
    def resolver(self):
        return get_resolver()

    def test_exact_match(self, resolver):
        """Names already in canonical form should return unchanged."""
        # Summary has these exact names
        result = resolver.resolve("Harry Morrison", "Hawthorn")
        assert result == "Harry Morrison"

    def test_nickname_variant(self, resolver):
        """Formal names should resolve to the canonical form from summary."""
        # Summary uses "Zachary Merrett" as canonical
        result = resolver.resolve("Zachary Merrett", "Essendon")
        assert result == "Zachary Merrett"

    def test_nickname_variant_lachie(self, resolver):
        result = resolver.resolve("Lachlan Ash", "GWS Giants")
        assert result == "Lachlan Ash"

    def test_nickname_variant_tim(self, resolver):
        result = resolver.resolve("Timothy English", "Western Bulldogs")
        assert result == "Timothy English"

    def test_abbreviated_name(self, resolver):
        """A. Cadman should resolve to Aaron Cadman."""
        result = resolver.resolve("A. Cadman", "GWS Giants")
        assert result == "Aaron Cadman"

    def test_abbreviated_sydney(self, resolver):
        """C. Mills should resolve via initial or surname+team."""
        result = resolver.resolve("C. Mills", "Sydney")
        assert result == "Callum Mills"

    def test_resolve_preserves_unknown(self, resolver):
        """Unknown names should be returned unchanged."""
        result = resolver.resolve("Nonexistent Player", "Adelaide")
        assert result == "Nonexistent Player"

    def test_stats(self, resolver):
        """Resolver should report reasonable index sizes."""
        stats = resolver.stats()
        assert stats["canonical_players"] > 600
        assert stats["exact_keys"] > stats["canonical_players"]
        assert stats["surname_team_keys"] > 500

    def test_resolve_df(self, resolver):
        """Vectorized resolution should work on DataFrames."""
        import pandas as pd
        df = pd.DataFrame({
            "Player": ["Zachary Merrett", "A. Cadman", "Harry Morrison"],
            "Team": ["Essendon", "GWS Giants", "Hawthorn"],
        })
        result = resolver.resolve_df(df, "Player", "Team")
        assert result.iloc[0] == "Zachary Merrett"
        assert result.iloc[1] == "Aaron Cadman"
        assert result.iloc[2] == "Harry Morrison"
