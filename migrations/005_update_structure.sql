-- Migration: Update structure - move season data to seasons table
-- Date: 2026-01-26

-- Step 1: Remove season-related columns from series table (they're now in seasons)
ALTER TABLE series DROP COLUMN season;
ALTER TABLE series DROP COLUMN year;
ALTER TABLE series DROP COLUMN episode_count;
ALTER TABLE series DROP COLUMN total_size_human;
ALTER TABLE series DROP COLUMN quality;

-- Step 2: Migrate existing data from series to seasons
-- Insert seasons from current series data
INSERT INTO seasons (series_id, season_number, year, episode_count, total_size_human, quality, created_at)
SELECT
    id as series_id,
    1 as season_number,  -- Default to season 1 for existing data
    NULL as year,        -- Will be extracted from title
    0 as episode_count,  -- Will be recalculated
    NULL as total_size_human,
    NULL as quality,
    created_at
FROM series
WHERE NOT EXISTS (
    SELECT 1 FROM seasons s WHERE s.series_id = series.id
);

-- Step 3: Update torrents to link to seasons
-- Link torrents to the newly created season
UPDATE torrents t
INNER JOIN seasons s ON t.series_id = s.series_id
SET t.season_id = s.id
WHERE t.season_id IS NULL;

-- Step 4: Remove old series_id foreign key from torrents (keeping season_id)
-- (We'll keep both columns for now during transition, can drop series_id later)
-- ALTER TABLE torrents DROP FOREIGN KEY torrents_ibfk_1;
-- ALTER TABLE torrents DROP COLUMN series_id;
