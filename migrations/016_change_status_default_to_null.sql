-- Migration: Change status column default to NULL
-- Status should be NULL (not downloaded) rather than 0 (failed)

-- First, update any existing 0 values to NULL
UPDATE torrents SET status = NULL WHERE status = 0;

-- Change column default to NULL
ALTER TABLE torrents MODIFY COLUMN status TINYINT NULL COMMENT 'Download status: NULL=not downloaded, 0=failed, 1=success';
