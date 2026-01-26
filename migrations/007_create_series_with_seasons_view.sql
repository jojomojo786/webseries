-- Create a view that combines series with their seasons
-- This makes it easier to query and view series data

CREATE OR REPLACE VIEW series_with_seasons AS
SELECT
    s.id,
    s.title,
    s.url,
    s.created_at,
    s.updated_at,
    COUNT(seas.id) as season_count,
    MIN(seas.season_number) as first_season,
    MAX(seas.season_number) as last_season,
    GROUP_CONCAT(DISTINCT seas.quality ORDER BY seas.quality SEPARATOR ', ') as available_qualities
FROM series s
LEFT JOIN seasons seas ON s.id = seas.series_id
GROUP BY s.id
ORDER BY s.created_at DESC;
