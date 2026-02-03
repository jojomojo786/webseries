-- Extend metadata columns to handle TV series with many writers/directors/cast
-- Issue: The Witcher and similar series have 100+ writers, exceeding VARCHAR(255)

-- Increase writers column size
ALTER TABLE series MODIFY COLUMN writers VARCHAR(1024) NULL;

-- Also extend other metadata columns that might exceed limits
ALTER TABLE series MODIFY COLUMN directors VARCHAR(512) NULL;
ALTER TABLE series MODIFY COLUMN cast VARCHAR(2048) NULL;
ALTER TABLE series MODIFY COLUMN production_companies VARCHAR(512) NULL;
ALTER TABLE series MODIFY COLUMN networks VARCHAR(512) NULL;
ALTER TABLE series MODIFY COLUMN creators VARCHAR(512) NULL;

-- For episodes table (episode writers/directors)
ALTER TABLE episodes MODIFY COLUMN writer VARCHAR(512) NULL;
ALTER TABLE episodes MODIFY COLUMN director VARCHAR(512) NULL;
ALTER TABLE episodes MODIFY COLUMN guest_stars VARCHAR(1024) NULL;
