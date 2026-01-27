# Web Series Management - Complete Workflow Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Scraping Workflow](#scraping-workflow)
3. [Download Workflow](#download-workflow)
4. [Episode Management Workflow](#episode-management-workflow)
5. [Database Schema](#database-schema)

---

## System Overview

```mermaid
graph TB
    subgraph "Scraping Phase"
        A[1TamilMV Forum] --> B[Scraper]
        B --> C[webseries.json]
        B --> D[(MySQL Database)]
    end

    subgraph "Download Phase"
        D --> E[Download Command]
        E --> F[qBittorrent]
        F --> G[downloads/temp/]
    end

    subgraph "Completion Phase"
        G --> H[Move-Completed Command]
        H --> I[downloads/completed/]
    end

    subgraph "Episode Management"
        I --> J[Episode Import]
        J --> D
        D --> K[AI Finder]
        K --> D
        D --> L[Fetch Metadata]
        L --> D
    end
```

---

## Scraping Workflow

### High-Level Scraping Flow

```mermaid
graph LR
    START[bd run] --> CMD[CLI Entry Point]
    CMD --> SCRAPER[scraper.py]
    SCRAPER --> FORUM[Fetch 1TamilMV Forum]
    FORUM --> PARSE[Parse Topics]
    PARSE --> FILTER[Apply Quality Filter]
    FILTER --> OUTPUT[Generate Outputs]

    OUTPUT --> JSON[webseries.json]
    OUTPUT --> DB[(Database Save)]

    style START fill:#e1f5e1
    style SCRAPER fill:#ffe1e1
    style DB fill:#e1e1ff
```

### Detailed Scraping Process

```mermaid
graph TD
    A[User runs: bd run] --> B{CLI Options}
    B --> |Default| C[Scrape All Pages]
    B --> |--pages N| D[Scrape N Pages]
    B --> |--no-db| E[Skip Database Save]
    B --> |--no-json| F[Skip JSON Output]

    C --> G[scraper.py: main]
    D --> G

    G --> H[Fetch Forum Listing]
    H --> I{Sort Order}
    I --> |start_date| J[Newest Topics]
    I --> |last_post| K[Recently Updated]

    J --> L[Parse Topic List]
    K --> L

    L --> M[For Each Topic]
    M --> N[Fetch Topic Page]
    N --> O[Extract Data]
    O --> P[Title]
    O --> Q[URL]
    O --> R[Poster Image]
    O --> S[Torrents]
    O --> T[Forum Date]

    S --> U{Process Torrents}
    U --> V[Extract Magnet Links]
    U --> W[Parse .torrent Files]
    U --> X[Get Quality/Size]

    V --> Y[Quality Filtering]
    W --> Y
    X --> Y

    Y --> Z{Passes Filter?}
    Z --> |Yes| AA[Keep Torrent]
    Z --> |No| AB[Discard]

    AA --> AC[Group by Episode Range]
    AC --> AD[Select Best Quality]

    AD --> AE[Save to JSON]
    AD --> AF[Save to Database]

    style A fill:#e1f5e1
    style G fill:#ffe1e1
    style AF fill:#e1e1ff
    style Z fill:#fff4e1
```

### Quality Filtering Logic

```mermaid
graph TD
    A[Torrent List] --> B{Has Quality Info?}
    B --> |No| C[Include All]
    B --> |Yes| D{Check Quality}

    D --> E{Preferred Quality?}
    E --> |1080p| F[Priority 1]
    E --> |720p| G[Priority 2]
    E --> |480p| H[Priority 3]
    E --> |4K| I[Exclude by Default]

    F --> J{Same Episode Range?}
    G --> J
    H --> J

    J --> |Yes| K[Keep Largest File]
    J --> |No| L[Keep Both]

    K --> M[Final Torrent List]
    L --> M
    C --> M
    I --> N[Discard]

    I[Exclude] --> N[4K Torrents]

    style F fill:#d4edda
    style G fill:#fff3cd
    style H fill:#f8d7da
    style I fill:#f8d7da
```

### Data Flow: Web to Database

```mermaid
graph LR
    subgraph "Source"
        WEB[1TamilMV Forum]
    end

    subgraph "Scraper"
        S1[Fetch Topics]
        S2[Parse Pages]
        S3[Extract Data]
        S4[Filter Quality]
    end

    subgraph "Transform"
        T1[Parse Title]
        T2[Extract Season]
        T3[Extract Year]
        T4[Calculate Episodes]
        T5[Get Info Hash]
    end

    subgraph "Database"
        DB1[(series)]
        DB2[(seasons)]
        DB3[(torrents)]
        DB4[(episodes)]
    end

    WEB --> S1 --> S2 --> S3 --> S4
    S4 --> T1 --> T2 --> T3 --> T4 --> T5
    T5 --> DB1
    T5 --> DB2
    T5 --> DB3
    T5 --> DB4

    style WEB fill:#e1f5e1
    style S4 fill:#ffe1e1
    style T5 fill:#fff4e1
    style DB1 fill:#e1e1ff
    style DB2 fill:#e1e1ff
    style DB3 fill:#e1e1ff
    style DB4 fill:#e1e1ff
```

---

## Download Workflow

### Download Process Flow

```mermaid
graph TD
    A[bd download] --> B[Query Database]
    B --> C{Filter Options}
    C --> |--series-id| D[Filter by Series]
    C --> |--season-id| E[Filter by Season]
    C --> |--quality| F[Filter by Quality]
    C --> |--limit| G[Limit Results]

    D --> H[Pending Torrents]
    E --> H
    F --> H
    G --> H

    H --> I[Connect qBittorrent]
    I --> J{Connected?}
    J --> |No| K[Error: Connection Failed]
    J --> |Yes| L[Add Torrents]

    L --> M[Set Save Path: temp/]
    M --> N[Update DB: downloading]
    N --> O[Monitor Progress]

    O --> P{Download Complete?}
    P --> |No| O
    P --> |Yes| Q[Move-Completed Trigger]

    Q --> R[Move: temp → completed/]
    R --> S[Update DB: completed]

    style A fill:#e1f5e1
    style K fill:#f8d7da
    style S fill:#d4edda
```

### qBittorrent Integration

```mermaid
graph LR
    subgraph "Database"
        DB[(torrents table)]
    end

    subgraph "Download Command"
        CMD[bd download]
        QB[qBittorrent Client]
    end

    subgraph "File System"
        TEMP[downloads/temp/]
        COMP[downloads/completed/]
    end

    DB --> |magnet links| CMD
    CMD --> |add torrent| QB
    QB --> |downloading| TEMP
    QB --> |100% complete| COMP
    COMP --> |update| DB

    style DB fill:#e1e1ff
    style TEMP fill:#fff4e1
    style COMP fill:#d4edda
```

---

## Episode Management Workflow

### Complete Episode Pipeline

```mermaid
graph TD
    A[Completed Downloads] --> B[bd episodes --import-db]
    B --> C[Scan downloads/completed/]
    C --> D[Parse Filenames]
    D --> E[Extract Metadata]
    E --> F[Insert into episodes table]

    F --> G[bd --finder poster.jpg]
    G --> H[AI Vision Analysis]
    H --> I[Detect Series Name]
    I --> J[Search TMDB]
    J --> K[Get tmdb_id + imdb_id]
    K --> L[Update series table]

    L --> M[bd episodes --fetch-metadata]
    M --> N[Query TMDB API]
    N --> O[Get Episode Details]
    O --> P[Names, Overviews, Air Dates]
    P --> Q[Update episodes table]

    Q --> R[bd episodes --validate]
    R --> S{Episode Count Match?}
    S --> |Yes| T[Valid Series]
    S --> |No| U[Flag for Review]

    style A fill:#e1f5e1
    style H fill:#ffe1e1
    style K fill:#fff4e1
    style T fill:#d4edda
    style U fill:#f8d7da
```

### AI-Powered Series Identification

```mermaid
graph LR
    A[Poster Image] --> B[OpenRouter GPT-5]
    B --> C[Image Analysis]
    C --> D[Extract Series Info]
    D --> E[Series Name]
    D --> F[Language]
    D --> G[Year]

    E --> H[TMDB Search]
    F --> H
    G --> H

    H --> I[Find Exact Match]
    I --> J[Get tmdb_id]
    I --> K[Get imdb_id]

    J --> L[Update Database]
    K --> L

    style A fill:#e1f5e1
    style B fill:#ffe1e1
    style L fill:#e1e1ff
```

---

## Database Schema

### Tables and Relationships

```mermaid
erDiagram
    series ||--o{ seasons : has
    seasons ||--o{ torrents : contains
    seasons ||--o{ episodes : tracks

    series {
        int id PK
        string title
        string url
        string poster_url
        string tmdb_id
        string imdb_id
        date forum_date
        date created_at
    }

    seasons {
        int id PK
        int series_id FK
        int season_number
        int episode_count
        string quality
        string size
        date created_at
    }

    torrents {
        int id PK
        int season_id FK
        string magnet_link
        string info_hash
        string quality
        string size
        int status
        date created_at
    }

    episodes {
        int id PK
        int season_id FK
        int episode_number
        string filename
        string name
        string overview
        date air_date
        boolean has_file
    }
```

### Status Values

| Table | Status | Meaning |
|-------|--------|---------|
| torrents | 0 | Pending download |
| torrents | 1 | Downloading |
| torrents | 2 | Completed |

---

## Quick Reference Commands

| Command | Purpose |
|---------|---------|
| `bd run` | Scrape forum and save to DB |
| `bd run --pages 5` | Scrape 5 pages only |
| `bd scrape --no-db` | Scrape to JSON only |
| `bd download` | Start downloads from DB |
| `bd download --quality 1080p` | Download 1080p only |
| `bd download --check-status` | Verify qBittorrent status |
| `bd move-completed` | Move finished downloads |
| `bd episodes --import-db` | Import files to episodes table |
| `bd --finder poster.jpg` | AI series identification |
| `bd episodes --fetch-metadata` | Get TMDB episode data |
| `bd episodes --validate` | Validate episode counts |

---

## File Locations

| Component | Path |
|-----------|------|
| Scraper | `Core Application/scraper.py` |
| CLI | `Core Application/cli.py` |
| Database | `Core Application/db.py` |
| Downloads | `downloads/temp/`, `downloads/completed/` |
| JSON Data | `data/webseries.json` |
| Config | `Configuration/config.yaml` |
