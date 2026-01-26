-- Migration: Drop size_bytes column from torrents table
-- The size_human field is sufficient for display purposes

-- Drop the size_bytes column
ALTER TABLE torrents DROP COLUMN size_bytes;
