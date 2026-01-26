-- Migration: Fix season column type and add total_size_human
-- Date: 2026-01-26

-- Note: MySQL doesn't support DROP COLUMN IF EXISTS, so we check manually first

-- Change season from VARCHAR(10) to INT (store 1 instead of S01)
ALTER TABLE series MODIFY COLUMN season INT NULL COMMENT 'Season number (1, 2, etc.)';

-- Add total_size_human column for human-readable display if it doesn't exist
ALTER TABLE series ADD COLUMN total_size_human VARCHAR(50) NULL COMMENT 'Human readable total size (e.g., 12.5 GB)' AFTER total_size;
