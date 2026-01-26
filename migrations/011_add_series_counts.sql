-- Migration: Add total_seasons and total_episodes to series table with auto-update triggers
-- Date: 2026-01-26

-- Add columns to series table
ALTER TABLE series ADD COLUMN total_seasons INT DEFAULT 0 AFTER imdb_id;
ALTER TABLE series ADD COLUMN total_episodes INT DEFAULT 0 AFTER total_seasons;

-- Drop existing triggers if they exist
DROP TRIGGER IF EXISTS trg_seasons_insert;
DROP TRIGGER IF EXISTS trg_seasons_delete;
DROP TRIGGER IF EXISTS trg_seasons_update;
DROP TRIGGER IF EXISTS trg_episodes_insert;
DROP TRIGGER IF EXISTS trg_episodes_delete;
DROP TRIGGER IF EXISTS trg_episodes_update;

-- Trigger: Update series.total_seasons when season is INSERTED
DELIMITER //
CREATE TRIGGER trg_seasons_insert AFTER INSERT ON seasons
FOR EACH ROW
BEGIN
    UPDATE series SET
        total_seasons = (SELECT COUNT(*) FROM seasons WHERE series_id = NEW.series_id),
        total_episodes = (SELECT COALESCE(SUM(episode_count), 0) FROM seasons WHERE series_id = NEW.series_id)
    WHERE id = NEW.series_id;
END//
DELIMITER ;

-- Trigger: Update series.total_seasons when season is DELETED
DELIMITER //
CREATE TRIGGER trg_seasons_delete AFTER DELETE ON seasons
FOR EACH ROW
BEGIN
    UPDATE series SET
        total_seasons = (SELECT COUNT(*) FROM seasons WHERE series_id = OLD.series_id),
        total_episodes = (SELECT COALESCE(SUM(episode_count), 0) FROM seasons WHERE series_id = OLD.series_id)
    WHERE id = OLD.series_id;
END//
DELIMITER ;

-- Trigger: Update series.total_episodes when season.episode_count is UPDATED
DELIMITER //
CREATE TRIGGER trg_seasons_update AFTER UPDATE ON seasons
FOR EACH ROW
BEGIN
    IF OLD.episode_count != NEW.episode_count OR OLD.series_id != NEW.series_id THEN
        -- Update old series if series_id changed
        IF OLD.series_id != NEW.series_id THEN
            UPDATE series SET
                total_seasons = (SELECT COUNT(*) FROM seasons WHERE series_id = OLD.series_id),
                total_episodes = (SELECT COALESCE(SUM(episode_count), 0) FROM seasons WHERE series_id = OLD.series_id)
            WHERE id = OLD.series_id;
        END IF;
        -- Update current series
        UPDATE series SET
            total_seasons = (SELECT COUNT(*) FROM seasons WHERE series_id = NEW.series_id),
            total_episodes = (SELECT COALESCE(SUM(episode_count), 0) FROM seasons WHERE series_id = NEW.series_id)
        WHERE id = NEW.series_id;
    END IF;
END//
DELIMITER ;

-- Backfill existing data
UPDATE series s SET
    total_seasons = (SELECT COUNT(*) FROM seasons WHERE series_id = s.id),
    total_episodes = (SELECT COALESCE(SUM(episode_count), 0) FROM seasons WHERE series_id = s.id);
