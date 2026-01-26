-- Migration: Add extended metadata fields to series table
-- Date: 2026-01-26

-- Status and dates
ALTER TABLE series ADD COLUMN status VARCHAR(30) NULL AFTER backdrop_url;
ALTER TABLE series ADD COLUMN first_air_date DATE NULL AFTER status;
ALTER TABLE series ADD COLUMN last_air_date DATE NULL AFTER first_air_date;
ALTER TABLE series ADD COLUMN end_year INT NULL AFTER last_air_date;

-- Credits
ALTER TABLE series ADD COLUMN cast TEXT NULL AFTER end_year;
ALTER TABLE series ADD COLUMN directors VARCHAR(255) NULL AFTER cast;
ALTER TABLE series ADD COLUMN writers VARCHAR(255) NULL AFTER directors;
ALTER TABLE series ADD COLUMN created_by VARCHAR(255) NULL AFTER writers;

-- Additional info
ALTER TABLE series ADD COLUMN original_title VARCHAR(255) NULL AFTER name;
ALTER TABLE series ADD COLUMN tagline VARCHAR(255) NULL AFTER summary;
ALTER TABLE series ADD COLUMN keywords VARCHAR(500) NULL AFTER genres;
ALTER TABLE series ADD COLUMN content_rating VARCHAR(20) NULL AFTER language;
ALTER TABLE series ADD COLUMN origin_country VARCHAR(100) NULL AFTER content_rating;
ALTER TABLE series ADD COLUMN networks VARCHAR(255) NULL AFTER origin_country;
ALTER TABLE series ADD COLUMN production_companies VARCHAR(255) NULL AFTER networks;

-- Technical
ALTER TABLE series ADD COLUMN episode_runtime INT NULL AFTER rating;
ALTER TABLE series ADD COLUMN vote_count INT NULL AFTER episode_runtime;
ALTER TABLE series ADD COLUMN is_adult TINYINT(1) DEFAULT 0 AFTER vote_count;
ALTER TABLE series ADD COLUMN in_production TINYINT(1) DEFAULT 0 AFTER is_adult;

-- Indexes
CREATE INDEX idx_status ON series(status);
CREATE INDEX idx_first_air_date ON series(first_air_date);
CREATE INDEX idx_content_rating ON series(content_rating);
CREATE INDEX idx_origin_country ON series(origin_country);
