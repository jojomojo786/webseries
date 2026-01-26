-- Migration: Fix orphan torrents (link them to seasons)
-- Date: 2026-01-26

-- Link orphan torrents to their series' season
-- For existing data, all series should have season 1
UPDATE torrents t
INNER JOIN seasons s ON t.series_id = s.series_id
SET t.season_id = s.id
WHERE t.season_id IS NULL;

-- Verify no orphans remain
-- SELECT COUNT(*) as remaining_orphans FROM torrents WHERE season_id IS NULL;
