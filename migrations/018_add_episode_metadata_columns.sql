-- Migration: Add episode metadata columns for TMDB data
-- Date: 2026-01-26

ALTER TABLE episodes ADD COLUMN imdb_id VARCHAR(20) NULL COMMENT 'IMDB ID for this episode' AFTER torrent_id;
ALTER TABLE episodes ADD COLUMN name VARCHAR(255) NULL COMMENT 'Episode title' AFTER imdb_id;
ALTER TABLE episodes ADD COLUMN overview TEXT NULL COMMENT 'Episode description/summary' AFTER name;
ALTER TABLE episodes ADD COLUMN air_date DATE NULL COMMENT 'Original air date' AFTER overview;
ALTER TABLE episodes ADD COLUMN still_url VARCHAR(512) NULL COMMENT 'Episode thumbnail image URL' AFTER air_date;
ALTER TABLE episodes ADD COLUMN vote_average DECIMAL(3,1) NULL COMMENT 'Episode rating (0-10)' AFTER still_url;
ALTER TABLE episodes ADD COLUMN vote_count INT NULL COMMENT 'Number of votes' AFTER vote_average;
ALTER TABLE episodes ADD COLUMN director VARCHAR(255) NULL COMMENT 'Episode director' AFTER vote_count;
ALTER TABLE episodes ADD COLUMN writer VARCHAR(255) NULL COMMENT 'Episode writer(s)' AFTER director;
ALTER TABLE episodes ADD COLUMN guest_stars VARCHAR(512) NULL COMMENT 'Guest stars in this episode' AFTER writer;

CREATE INDEX idx_imdb_id ON episodes(imdb_id);
