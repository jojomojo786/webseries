-- Migration: Remove languages column (not needed)
-- Date: 2026-01-26

-- Drop the languages column from series table
ALTER TABLE series DROP COLUMN languages;
