-- PD TeamTracker normalised SQLite schema.
-- All primary keys are composite and stable so rescrapes can upsert safely.

CREATE TABLE IF NOT EXISTS matches (
    match_id           TEXT PRIMARY KEY,           -- slug like "mentone_grammar_vs_assumption"
    season             INTEGER NOT NULL,
    round              TEXT NOT NULL,
    home_team          TEXT,
    away_team          TEXT,
    home_score         INTEGER,
    away_score         INTEGER,
    home_goals_behinds TEXT,
    away_goals_behinds TEXT,
    card_label         TEXT,
    scraped_at         TEXT NOT NULL,
    raw_json_path      TEXT
);
CREATE INDEX IF NOT EXISTS idx_matches_season_round ON matches(season, round);

-- Team-level stat cells from Summary / Efficiencies / Free Kicks (one row per
-- (match, period, section, stat, side)). The ``value_type`` column flags
-- whether the value is a counter, pct, ratio, etc.
CREATE TABLE IF NOT EXISTS team_match_stats (
    match_id   TEXT NOT NULL,
    period     TEXT NOT NULL,        -- TOTAL/Q1/Q2/Q3/Q4
    tab        TEXT NOT NULL,        -- summary / efficiencies / free_kicks
    section    TEXT,
    stat_name  TEXT NOT NULL,
    side       TEXT NOT NULL,        -- home / away / diff / meta
    value      TEXT,                 -- stored as text; interpret via value_type
    value_num  REAL,                 -- best-effort numeric coercion
    value_type TEXT,                 -- int / float / pct / ratio / text
    PRIMARY KEY (match_id, period, tab, section, stat_name, side),
    FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

-- Score sources breakdown (home/away scoreline + % per category per period)
CREATE TABLE IF NOT EXISTS score_sources (
    match_id         TEXT NOT NULL,
    period           TEXT NOT NULL,
    parent           TEXT NOT NULL DEFAULT '',
    name             TEXT NOT NULL,
    home_scoreline   TEXT,
    home_pct         TEXT,
    away_scoreline   TEXT,
    away_pct         TEXT,
    PRIMARY KEY (match_id, period, parent, name),
    FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

-- Shot-map: the tabular shot log (time/type/team/player/source/assist).
-- Coordinates are not yet captured (SVG chart only).
CREATE TABLE IF NOT EXISTS shots (
    match_id TEXT NOT NULL,
    period   TEXT NOT NULL,
    idx      INTEGER NOT NULL,       -- row index within (match_id, period)
    time     TEXT,
    type     TEXT,
    team     TEXT,
    player   TEXT,
    source   TEXT,
    assist   TEXT,
    PRIMARY KEY (match_id, period, idx),
    FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

-- Player stats: long format. One row per (match, period, view, player, stat).
CREATE TABLE IF NOT EXISTS player_match_stats (
    match_id   TEXT NOT NULL,
    period     TEXT NOT NULL,
    view       TEXT NOT NULL,        -- Basic / Advanced / Involvements
    side       TEXT NOT NULL,        -- home / away (derived from team_filter)
    team       TEXT,                 -- canonical team name (from header)
    jumper     INTEGER,
    player     TEXT NOT NULL,
    stat_name  TEXT NOT NULL,
    value      TEXT,
    value_num  REAL,
    PRIMARY KEY (match_id, period, view, side, player, stat_name),
    FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

-- Efficiency ratios (disposal/kick/handball % with numerator/denominator)
CREATE TABLE IF NOT EXISTS efficiency_ratios (
    match_id   TEXT NOT NULL,
    period     TEXT NOT NULL,
    section    TEXT NOT NULL DEFAULT '',
    name       TEXT NOT NULL,
    home_pct   TEXT,
    home_ratio TEXT,
    away_pct   TEXT,
    away_ratio TEXT,
    PRIMARY KEY (match_id, period, section, name),
    FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

-- Pies (stoppages / clearances won-lost-neutral)
CREATE TABLE IF NOT EXISTS pie_stats (
    match_id TEXT NOT NULL,
    period   TEXT NOT NULL,
    section  TEXT NOT NULL DEFAULT '',
    name     TEXT NOT NULL,
    side     TEXT NOT NULL DEFAULT '',
    value    TEXT,
    labels   TEXT,              -- JSON array of labels
    PRIMARY KEY (match_id, period, section, name, side),
    FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

-- Derived views -------------------------------------------------------------
-- Per-player appearance index: one row per (team, player) aggregating the
-- matches they've appeared in.
CREATE VIEW IF NOT EXISTS pd_players AS
SELECT
    team,
    player,
    MAX(jumper)                 AS jumper_latest,
    COUNT(DISTINCT match_id)    AS matches,
    MIN(m.season)               AS first_season,
    MAX(m.season)               AS last_season,
    GROUP_CONCAT(DISTINCT m.season) AS seasons
FROM player_match_stats p
JOIN matches m USING (match_id)
WHERE p.period = 'TOTAL' AND p.view = 'Basic'
GROUP BY team, player;

-- Per-player per-match summary (totals only, Basic view pivoted back to wide).
CREATE VIEW IF NOT EXISTS pd_player_match_totals AS
SELECT
    match_id, side, team, jumper, player, stat_name, value_num
FROM player_match_stats
WHERE period = 'TOTAL' AND view = 'Basic';
