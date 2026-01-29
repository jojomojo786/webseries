-- Migration: Add local image paths to series table
-- Date: 2026-01-29
-- Purpose: Store local paths for downloaded poster and cover images

-- Add local_poster_path column
ALTER TABLE series ADD COLUMN local_poster_path VARCHAR(512) NULL COMMENT 'Local poster image path' AFTER backdrop_url;

-- Add local_cover_path column
ALTER TABLE series ADD COLUMN local_cover_path VARCHAR(512) NULL COMMENT 'Local backdrop/cover image path' AFTER local_poster_path;

-- Add index for faster lookups
CREATE INDEX idx_local_poster_path ON series(local_poster_path);
CREATE INDEX idx_local_cover_path ON series(local_cover_path);
