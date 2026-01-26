-- Migration: Add poster_url column to series table
-- Date: 2026-01-26

ALTER TABLE series ADD COLUMN poster_url VARCHAR(512) NULL AFTER url;
