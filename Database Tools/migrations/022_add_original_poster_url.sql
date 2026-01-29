-- Migration: Add original_poster_url column to series table
-- Date: 2026-01-29
-- Purpose: Store the original scraped poster URL separately from TMDB poster URL
--          This prevents AI from analyzing wrong posters when previous matches were incorrect

-- Add original_poster_url column after poster_url
ALTER TABLE series ADD COLUMN original_poster_url VARCHAR(512) NULL COMMENT 'Original poster URL from scraping (never updated)' AFTER poster_url;

-- Add index for faster lookups
CREATE INDEX idx_original_poster_url ON series(original_poster_url);

-- Migrate existing data: copy current poster_url to original_poster_url
-- This preserves the original posters for existing series
UPDATE series SET original_poster_url = poster_url WHERE original_poster_url IS NULL AND poster_url IS NOT NULL;
