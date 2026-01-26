-- Migration: Create seasons table for normalized structure
-- Date: 2026-01-26

-- Create seasons table
CREATE TABLE IF NOT EXISTS seasons (
    id INT AUTO_INCREMENT PRIMARY KEY,
    series_id INT NOT NULL,
    season_number INT NOT NULL COMMENT 'Season number (1, 2, 3, etc.)',
    year INT NULL COMMENT 'Year extracted from title',
    episode_count INT DEFAULT 0 COMMENT 'Number of episodes',
    total_size_human VARCHAR(50) NULL COMMENT 'Human readable total size (e.g., 12.5 GB)',
    quality VARCHAR(20) NULL COMMENT 'Best quality available (1080p, 720p, etc.)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE,
    UNIQUE KEY unique_series_season (series_id, season_number),
    INDEX idx_series_id (series_id),
    INDEX idx_year (year),
    INDEX idx_quality (quality)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Update torrents to reference seasons instead of series
-- First, add the season_id column
ALTER TABLE torrents ADD COLUMN season_id INT NULL AFTER series_id;

-- Add foreign key constraint
ALTER TABLE torrents ADD CONSTRAINT fk_torrents_season
    FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE CASCADE;

-- Create index on season_id
CREATE INDEX idx_season_id ON torrents(season_id);
