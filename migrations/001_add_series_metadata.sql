-- Migration: Add lightweight metadata to series table
-- Date: 2026-01-26

-- Add new columns to series table
ALTER TABLE series
ADD COLUMN year INT NULL COMMENT 'Year extracted from title',
ADD COLUMN season VARCHAR(10) NULL COMMENT 'Season (S01, S02, etc.)',
ADD COLUMN episode_count INT DEFAULT 0 COMMENT 'Number of episodes (calculated from torrent names)',
ADD COLUMN total_size BIGINT DEFAULT 0 COMMENT 'Total size in bytes',
ADD COLUMN quality VARCHAR(20) NULL COMMENT 'Best quality available (1080p, 720p, etc.)';

-- Add index on year for filtering
CREATE INDEX idx_series_year ON series(year);

-- Add index on quality for filtering
CREATE INDEX idx_series_quality ON series(quality);
