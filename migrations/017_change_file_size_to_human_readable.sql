-- Migration: Change file_size column to human-readable format
-- Date: 2026-01-26

-- Convert existing byte values to human-readable format
UPDATE episodes SET file_size = CASE
    WHEN file_size >= 1099511627776 THEN CONCAT(file_size DIV 1099511627776, ' TB')
    WHEN file_size >= 1073741824 THEN CONCAT(file_size DIV 1073741824, ' GB')
    WHEN file_size >= 1048576 THEN CONCAT(file_size DIV 1048576, ' MB')
    WHEN file_size >= 1024 THEN CONCAT(file_size DIV 1024, ' KB')
    WHEN file_size > 0 THEN CONCAT(file_size, ' B')
    ELSE NULL
END
WHERE file_size IS NOT NULL;

-- Change column type to VARCHAR
ALTER TABLE episodes MODIFY COLUMN file_size VARCHAR(50) NULL COMMENT 'Human-readable file size (e.g., 1 GB, 500 MB)';
