-- Migration: Add metadata fields to series table
-- Date: 2026-01-26

ALTER TABLE series ADD COLUMN tmdb_id INT NULL AFTER imdb_id;
ALTER TABLE series ADD COLUMN name VARCHAR(255) NULL AFTER title;
ALTER TABLE series ADD COLUMN year INT NULL AFTER total_episodes;
ALTER TABLE series ADD COLUMN summary TEXT NULL AFTER year;
ALTER TABLE series ADD COLUMN genres VARCHAR(255) NULL AFTER summary;
ALTER TABLE series ADD COLUMN language VARCHAR(50) NULL AFTER genres;
ALTER TABLE series ADD COLUMN rating DECIMAL(3,1) NULL AFTER language;
ALTER TABLE series ADD COLUMN trailer_key VARCHAR(20) NULL AFTER rating;
ALTER TABLE series ADD COLUMN backdrop_url VARCHAR(512) NULL AFTER trailer_key;

-- Add indexes
CREATE INDEX idx_tmdb_id ON series(tmdb_id);
CREATE INDEX idx_year ON series(year);
CREATE INDEX idx_rating ON series(rating);
