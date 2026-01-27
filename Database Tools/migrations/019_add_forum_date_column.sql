-- Migration: Add forum_date column to series table
-- Date: 2026-01-27

-- Add forum_date column to store when the post was created on the forum
ALTER TABLE series ADD COLUMN forum_date DATETIME NULL COMMENT 'Forum post date from <time> datetime attribute' AFTER poster_url;

-- Add index for sorting by forum date
CREATE INDEX idx_series_forum_date ON series(forum_date);
