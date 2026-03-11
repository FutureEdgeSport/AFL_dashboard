"""
Integration Tests for AFL Dashboard Data Pipeline
===================================================
Tests that validate schema validation, safe I/O, notifications,
and the overall pipeline configuration are correct.

Run with:
    .venv/bin/python -m pytest tests/ -v
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================================
# SCHEMA VALIDATOR TESTS
# ============================================================================

class TestSchemaValidator:
    """Tests for utils/schema_validator.py."""

    def test_valid_csv_passes(self, tmp_path):
        """A CSV with all required columns and enough rows should pass."""
        from utils.schema_validator import validate_csv

        # Create a valid squads-like CSV
        players = []
        for i in range(350):
            team = f"Team{i % 18}"
            players.append({
                "Team": team,
                "Player": f"Player {i}",
                "Position": "Forward",
                "Season": 2026,
            })
        df = pd.DataFrame(players)
        csv_path = tmp_path / "data" / "raw" / "player" / "squads_2026.csv"
        csv_path.parent.mkdir(parents=True)
        df.to_csv(csv_path, index=False)

        schema = {
            "name": "squads",
            "path_template": "data/raw/player/squads_{season}.csv",
            "required_cols": ["Team", "Player", "Position", "Season"],
            "min_rows": 300,
            "non_null_cols": ["Team", "Player"],
            "optional": False,
        }

        with patch("utils.schema_validator.BASE_DIR", tmp_path):
            errors = validate_csv(schema, 2026)

        hard = [e for e in errors if not e.is_warning]
        assert len(hard) == 0, f"Unexpected hard errors: {hard}"

    def test_missing_required_csv_errors(self, tmp_path):
        """A missing required CSV should produce a hard error."""
        from utils.schema_validator import validate_csv

        schema = {
            "name": "squads",
            "path_template": "data/raw/player/squads_{season}.csv",
            "required_cols": ["Team", "Player"],
            "min_rows": 300,
            "non_null_cols": ["Team"],
            "optional": False,
        }

        with patch("utils.schema_validator.BASE_DIR", tmp_path):
            errors = validate_csv(schema, 2026)

        assert len(errors) == 1
        assert not errors[0].is_warning
        assert "not found" in errors[0].message.lower()

    def test_missing_optional_csv_warns(self, tmp_path):
        """A missing optional CSV should produce only a warning."""
        from utils.schema_validator import validate_csv

        schema = {
            "name": "traits",
            "path_template": "data/raw/traits/traits_{season}.csv",
            "required_cols": ["Player"],
            "min_rows": 100,
            "non_null_cols": [],
            "optional": True,
        }

        with patch("utils.schema_validator.BASE_DIR", tmp_path):
            errors = validate_csv(schema, 2026)

        assert len(errors) == 1
        assert errors[0].is_warning

    def test_too_few_rows_errors(self, tmp_path):
        """Fewer rows than min_rows should produce an error."""
        from utils.schema_validator import validate_csv

        df = pd.DataFrame({"Team": ["A", "B"], "Player": ["X", "Y"]})
        csv_path = tmp_path / "data" / "raw" / "player" / "squads_2026.csv"
        csv_path.parent.mkdir(parents=True)
        df.to_csv(csv_path, index=False)

        schema = {
            "name": "squads",
            "path_template": "data/raw/player/squads_{season}.csv",
            "required_cols": ["Team", "Player"],
            "min_rows": 300,
            "non_null_cols": [],
            "optional": False,
        }

        with patch("utils.schema_validator.BASE_DIR", tmp_path):
            errors = validate_csv(schema, 2026)

        msg = " ".join(str(e) for e in errors)
        assert "below minimum" in msg.lower()

    def test_missing_columns_errors(self, tmp_path):
        """Missing required columns should produce a hard error."""
        from utils.schema_validator import validate_csv

        df = pd.DataFrame({"Team": ["A"] * 20})
        csv_path = tmp_path / "data" / "raw" / "team" / "team_stats_2026.csv"
        csv_path.parent.mkdir(parents=True)
        df.to_csv(csv_path, index=False)

        schema = {
            "name": "team_stats",
            "path_template": "data/raw/team/team_stats_{season}.csv",
            "required_cols": ["Team", "Matches", "RatingPoints"],
            "min_rows": 10,
            "non_null_cols": [],
            "optional": False,
        }

        with patch("utils.schema_validator.BASE_DIR", tmp_path):
            errors = validate_csv(schema, 2026)

        hard = [e for e in errors if not e.is_warning]
        assert any("Missing required columns" in str(e) for e in hard)

    def test_high_null_rate_warns(self, tmp_path):
        """A column with >20% nulls should produce a warning."""
        from utils.schema_validator import validate_csv

        df = pd.DataFrame({
            "Team": [None] * 8 + ["A"] * 2,
            "Player": [f"P{i}" for i in range(10)],
        })
        csv_path = tmp_path / "data" / "raw" / "team" / "team_stats_2026.csv"
        csv_path.parent.mkdir(parents=True)
        df.to_csv(csv_path, index=False)

        schema = {
            "name": "team_stats",
            "path_template": "data/raw/team/team_stats_{season}.csv",
            "required_cols": ["Team"],
            "min_rows": 5,
            "non_null_cols": ["Team"],
            "optional": False,
        }

        with patch("utils.schema_validator.BASE_DIR", tmp_path):
            errors = validate_csv(schema, 2026)

        warnings = [e for e in errors if e.is_warning]
        assert any("null values" in str(w) for w in warnings)

    def test_validate_pipeline_schemas_against_real_data(self):
        """Run schema validation against the actual current data files."""
        from utils.schema_validator import validate_pipeline_schemas
        from config.constants import CURRENT_SEASON

        errors = validate_pipeline_schemas(CURRENT_SEASON)
        hard_errors = [e for e in errors if not e.is_warning]

        # The real data should pass all hard checks
        assert len(hard_errors) == 0, (
            f"Real pipeline data has schema errors:\n"
            + "\n".join(str(e) for e in hard_errors)
        )


# ============================================================================
# SAFE I/O TESTS
# ============================================================================

class TestSafeIO:
    """Tests for utils/safe_io.py."""

    def test_safe_csv_write_creates_file(self, tmp_path):
        """safe_csv_write should create the target file."""
        from utils.safe_io import safe_csv_write

        df = pd.DataFrame({"A": [1, 2, 3]})
        target = tmp_path / "output.csv"

        with patch("utils.safe_io.BACKUP_DIR", tmp_path / "backups"):
            safe_csv_write(df, target)

        assert target.exists()
        result = pd.read_csv(target)
        assert len(result) == 3

    def test_safe_csv_write_backs_up_existing(self, tmp_path):
        """If file already exists, it should be backed up before overwrite."""
        from utils.safe_io import safe_csv_write

        backup_dir = tmp_path / "backups"
        target = tmp_path / "output.csv"

        # Write original
        df1 = pd.DataFrame({"A": [1, 2]})
        df1.to_csv(target, index=False)

        # Overwrite with safe_csv_write
        df2 = pd.DataFrame({"A": [3, 4, 5]})
        with patch("utils.safe_io.BACKUP_DIR", backup_dir):
            safe_csv_write(df2, target)

        # New file should have new data
        result = pd.read_csv(target)
        assert len(result) == 3

        # Backup should exist
        backups = list(backup_dir.glob("output_*"))
        assert len(backups) == 1

    def test_safe_csv_write_no_temp_on_success(self, tmp_path):
        """No .tmp file should remain after a successful write."""
        from utils.safe_io import safe_csv_write

        df = pd.DataFrame({"A": [1]})
        target = tmp_path / "output.csv"

        with patch("utils.safe_io.BACKUP_DIR", tmp_path / "backups"):
            safe_csv_write(df, target)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_backup_rotation(self, tmp_path):
        """Only MAX_BACKUPS_PER_FILE should be kept."""
        from utils.safe_io import safe_csv_write, MAX_BACKUPS_PER_FILE

        backup_dir = tmp_path / "backups"
        target = tmp_path / "output.csv"

        df = pd.DataFrame({"A": [1]})

        # Write MAX + 2 times to trigger rotation
        for i in range(MAX_BACKUPS_PER_FILE + 2):
            with patch("utils.safe_io.BACKUP_DIR", backup_dir):
                safe_csv_write(df, target)

        backups = list(backup_dir.glob("output_*"))
        assert len(backups) <= MAX_BACKUPS_PER_FILE


# ============================================================================
# NOTIFICATION TESTS
# ============================================================================

class TestNotifications:
    """Tests for utils/notifications.py."""

    def test_email_noop_when_no_address(self):
        """Email notification should be a no-op if ALERT_EMAIL is empty."""
        from utils.notifications import send_email_notification

        with patch("utils.notifications.ALERT_EMAIL", ""):
            # Should not raise
            send_email_notification("Test", "message")

    def test_email_sends_via_smtp_when_configured(self):
        """Email notification should send via SMTP when credentials are set."""
        from utils.notifications import send_email_notification

        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch("utils.notifications.ALERT_EMAIL", "test@example.com"), \
             patch("utils.notifications.SMTP_USER", "sender@gmail.com"), \
             patch("utils.notifications.SMTP_PASSWORD", "secret"), \
             patch("utils.notifications.smtplib.SMTP", mock_smtp_class):
            send_email_notification("Title", "Body", is_error=True)

        mock_smtp_class.assert_called_once()
        mock_smtp_instance.sendmail.assert_called_once()
        call_args = mock_smtp_instance.sendmail.call_args[0]
        assert call_args[0] == "sender@gmail.com"
        assert call_args[1] == ["test@example.com"]

    def test_notify_calls_both_channels(self):
        """notify() should call both macOS and email notification functions."""
        import utils.notifications as notif

        with patch.object(notif, "send_macos_notification") as mock_mac, \
             patch.object(notif, "send_email_notification") as mock_email:
            notif.notify("Title", "Body", is_error=False)

        mock_mac.assert_called_once_with("Title", "Body")
        mock_email.assert_called_once_with("Title", "Body", is_error=False)


# ============================================================================
# PIPELINE CONFIGURATION TESTS
# ============================================================================

class TestPipelineConfig:
    """Tests for scheduled_update.py pipeline configuration."""

    def test_all_scripts_exist(self):
        """Every non-inline step should reference a script that exists."""
        sys.path.insert(0, str(ROOT))
        # Re-import fresh to get current UPDATE_STEPS
        import importlib
        import scheduled_update as su
        importlib.reload(su)

        missing = []
        for name, script, args, desc, slow in su.UPDATE_STEPS:
            if script is None:
                continue  # Inline step
            script_path = su.BASE_DIR / script
            if not script_path.exists():
                missing.append((name, script))

        assert len(missing) == 0, f"Missing scripts: {missing}"

    def test_dependency_steps_exist(self):
        """All steps referenced in STEP_DEPENDENCIES should exist in UPDATE_STEPS."""
        import importlib
        import scheduled_update as su
        importlib.reload(su)

        step_names = {s[0] for s in su.UPDATE_STEPS}

        for step, deps in su.STEP_DEPENDENCIES.items():
            assert step in step_names, f"Dependency key '{step}' not in UPDATE_STEPS"
            for dep in deps:
                assert dep in step_names, (
                    f"Dependency '{dep}' (required by '{step}') not in UPDATE_STEPS"
                )

    def test_no_circular_dependencies(self):
        """Dependency graph should have no cycles."""
        import importlib
        import scheduled_update as su
        importlib.reload(su)

        # Build adjacency: step -> list of dependencies
        deps = su.STEP_DEPENDENCIES

        def has_cycle(node, visited, rec_stack):
            visited.add(node)
            rec_stack.add(node)
            for dep in deps.get(node, []):
                if dep not in visited:
                    if has_cycle(dep, visited, rec_stack):
                        return True
                elif dep in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        visited = set()
        for step in deps:
            if step not in visited:
                assert not has_cycle(step, visited, set()), (
                    f"Circular dependency detected involving '{step}'"
                )

    def test_step_order_respects_dependencies(self):
        """Steps should appear after their dependencies in UPDATE_STEPS."""
        import importlib
        import scheduled_update as su
        importlib.reload(su)

        step_order = {s[0]: i for i, s in enumerate(su.UPDATE_STEPS)}

        for step, deps in su.STEP_DEPENDENCIES.items():
            if step not in step_order:
                continue
            for dep in deps:
                if dep not in step_order:
                    continue
                assert step_order[dep] < step_order[step], (
                    f"'{step}' (index {step_order[step]}) appears before "
                    f"its dependency '{dep}' (index {step_order[dep]})"
                )


# ============================================================================
# PARAMETERIZED SCRIPT TESTS
# ============================================================================

class TestParameterizedScripts:
    """Tests that parameterized scripts accept --season flag."""

    @pytest.mark.parametrize("script", [
        "scrape_footywire.py",
        "run_traits_api.py",
        "build_season_data.py",
    ])
    def test_script_accepts_season_flag(self, script):
        """Each parameterized script should accept --help without error."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(ROOT / script), "--help"],
            capture_output=True, text=True, timeout=15,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, f"{script} --help failed: {result.stderr}"
        assert "--season" in result.stdout, f"{script} does not accept --season"


# ============================================================================
# DATA-DIFF ALERTING TESTS
# ============================================================================

class TestDataDiff:
    """Tests for utils/data_diff.py."""

    def test_no_backup_returns_empty(self, tmp_path):
        """With no backup, diff check should return no issues."""
        from utils.data_diff import check_data_diff

        csv = tmp_path / "data.csv"
        pd.DataFrame({"A": [1, 2, 3]}).to_csv(csv, index=False)

        # Point backup dir to empty temp location
        import utils.data_diff as dd
        orig = dd.BACKUP_DIR
        dd.BACKUP_DIR = tmp_path / "empty_backups"
        try:
            issues = check_data_diff(csv)
            assert issues == []
        finally:
            dd.BACKUP_DIR = orig

    def test_detects_row_drop(self, tmp_path):
        """Should warn when rows drop significantly."""
        from utils.data_diff import check_data_diff

        backups = tmp_path / "backups"
        backups.mkdir()

        # Create backup with 100 rows
        backup_file = backups / "data_20260101_000000.csv"
        pd.DataFrame({"A": range(100)}).to_csv(backup_file, index=False)

        # Current file with 30 rows (70% drop)
        current = tmp_path / "data.csv"
        pd.DataFrame({"A": range(30)}).to_csv(current, index=False)

        import utils.data_diff as dd
        orig = dd.BACKUP_DIR
        dd.BACKUP_DIR = backups
        try:
            issues = check_data_diff(current)
            assert len(issues) == 1
            assert "ROW DROP" in issues[0] or "CRITICAL" in issues[0]
        finally:
            dd.BACKUP_DIR = orig

    def test_detects_missing_columns(self, tmp_path):
        """Should warn when columns are lost."""
        from utils.data_diff import check_data_diff

        backups = tmp_path / "backups"
        backups.mkdir()

        backup_file = backups / "data_20260101_000000.csv"
        pd.DataFrame({"A": [1], "B": [2], "C": [3]}).to_csv(backup_file, index=False)

        current = tmp_path / "data.csv"
        pd.DataFrame({"A": [1]}).to_csv(current, index=False)

        import utils.data_diff as dd
        orig = dd.BACKUP_DIR
        dd.BACKUP_DIR = backups
        try:
            issues = check_data_diff(current)
            assert any("COLUMNS LOST" in i for i in issues)
        finally:
            dd.BACKUP_DIR = orig

    def test_detects_empty_file(self, tmp_path):
        """Should flag when an output file has 0 rows."""
        from utils.data_diff import check_data_diff

        backups = tmp_path / "backups"
        backups.mkdir()

        backup_file = backups / "data_20260101_000000.csv"
        pd.DataFrame({"A": [1, 2, 3]}).to_csv(backup_file, index=False)

        current = tmp_path / "data.csv"
        pd.DataFrame({"A": pd.Series([], dtype=int)}).to_csv(current, index=False)

        import utils.data_diff as dd
        orig = dd.BACKUP_DIR
        dd.BACKUP_DIR = backups
        try:
            issues = check_data_diff(current)
            assert any("EMPTY" in i for i in issues)
        finally:
            dd.BACKUP_DIR = orig

    def test_diff_report_formats(self, tmp_path):
        """diff_report should produce a formatted string with all issues."""
        from utils.data_diff import diff_report

        backups = tmp_path / "backups"
        backups.mkdir()

        backup_file = backups / "data_20260101_000000.csv"
        pd.DataFrame({"A": range(100)}).to_csv(backup_file, index=False)

        current = tmp_path / "data.csv"
        pd.DataFrame({"A": range(10)}).to_csv(current, index=False)

        import utils.data_diff as dd
        orig = dd.BACKUP_DIR
        dd.BACKUP_DIR = backups
        try:
            report = diff_report([current])
            assert "Data-diff alerts" in report
            assert "ROW DROP" in report or "CRITICAL" in report
        finally:
            dd.BACKUP_DIR = orig

    def test_no_issues_returns_empty_report(self, tmp_path):
        """diff_report should return empty string when all is fine."""
        from utils.data_diff import diff_report

        # No backup → no issues
        import utils.data_diff as dd
        orig = dd.BACKUP_DIR
        dd.BACKUP_DIR = tmp_path / "empty"
        try:
            csv = tmp_path / "data.csv"
            pd.DataFrame({"A": [1, 2, 3]}).to_csv(csv, index=False)
            report = diff_report([csv])
            assert report == ""
        finally:
            dd.BACKUP_DIR = orig
