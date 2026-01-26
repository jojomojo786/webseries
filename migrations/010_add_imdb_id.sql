-- Migration: Add imdb_id column to series table
-- Date: 2026-01-26

ALTER TABLE series ADD COLUMN imdb_id VARCHAR(20) NULL AFTER poster_url;
CREATE INDEX idx_imdb_id ON series(imdb_id);
