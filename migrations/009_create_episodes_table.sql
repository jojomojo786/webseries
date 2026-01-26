-- Migration: Create episodes table to track downloaded episodes
-- Date: 2026-01-26

CREATE TABLE IF NOT EXISTS episodes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    season_id INT NOT NULL,
    episode_number INT NOT NULL,
    status ENUM('available', 'missing', 'corrupted', 'encoding') DEFAULT 'available',
    file_path VARCHAR(512) NULL COMMENT 'Path to the episode file',
    file_size BIGINT NULL COMMENT 'File size in bytes',
    quality VARCHAR(20) NULL COMMENT '1080p, 720p, etc.',
    duration INT NULL COMMENT 'Duration in seconds',
    torrent_id INT NULL COMMENT 'Source torrent this came from',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE CASCADE,
    FOREIGN KEY (torrent_id) REFERENCES torrents(id) ON DELETE SET NULL,
    UNIQUE KEY unique_season_episode (season_id, episode_number),
    INDEX idx_season_id (season_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
