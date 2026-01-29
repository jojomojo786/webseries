-- Migration: Add R2 upload status columns to series table
-- Date: 2026-01-29
-- Description: Track whether poster and cover images were successfully uploaded to R2

-- Add r2_poster column (1=success, 0=failed, NULL=not attempted)
ALTER TABLE series ADD COLUMN r2_poster TINYINT NULL DEFAULT NULL COMMENT 'R2 poster upload status: 1=success, 0=failed, NULL=not attempted';

-- Add r2_cover column (1=success, 0=failed, NULL=not attempted)
ALTER TABLE series ADD COLUMN r2_cover TINYINT NULL DEFAULT NULL COMMENT 'R2 cover upload status: 1=success, 0=failed, NULL=not attempted';
