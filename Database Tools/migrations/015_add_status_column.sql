-- Migration: Add status column to torrents table
-- Status: 0 = failed/pending, 1 = successfully downloaded

-- Add status column with default value 0 (pending/failed)
ALTER TABLE torrents ADD COLUMN status TINYINT DEFAULT 0 COMMENT 'Download status: 0=failed/pending, 1=success' AFTER quality;

-- Add index on status for faster queries
CREATE INDEX idx_status ON torrents(status);
