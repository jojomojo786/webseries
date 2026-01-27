# Episode Management Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EPISODE MANAGEMENT WORKFLOW                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  COMMAND: python3 "Core Application/cli.py" episodes                        │
│  (Default: --scan --use-ai --import-db)                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: SCAN FOLDER                                                        │
│  📁 /home/webseries/Data & Cache/downloads/completed                        │
│                                                                             │
│  For each video file:                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Regex Extraction                                                    │   │
│  │  ├── S01E01, S01 EP01, 1x01 patterns                                │   │
│  │  └── Extract: series_name, season, episode, quality                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                          │                                                  │
│              ┌───────────┴───────────┐                                      │
│              ▼                       ▼                                      │
│       ┌──────────┐           ┌──────────────┐                              │
│       │ SUCCESS  │           │   UNCLEAR?   │                              │
│       │ Regex OK │           │ Use AI Check │                              │
│       └────┬─────┘           └──────┬───────┘                              │
│            │                        │                                       │
│            │                        ▼                                       │
│            │         ┌──────────────────────────────┐                      │
│            │         │  gpt-5-nano (OpenRouter)     │                      │
│            │         │  ├── No episode number?      │                      │
│            │         │  ├── Series name < 3 chars?  │                      │
│            │         │  ├── Ends with "EP"?         │                      │
│            │         │  └── Batch range (1-5)?      │                      │
│            │         │                              │                      │
│            │         │  Returns: season, episode    │                      │
│            │         └──────────────────────────────┘                      │
│            │                        │                                       │
│            └────────────┬───────────┘                                       │
│                         ▼                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: IMPORT TO DATABASE                                                 │
│                                                                             │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                   │
│  │   series    │────▶│   seasons   │────▶│  episodes   │                   │
│  │   table     │     │   table     │     │   table     │                   │
│  └─────────────┘     └─────────────┘     └─────────────┘                   │
│                                                                             │
│  • Create series if not exists                                              │
│  • Create season if not exists                                              │
│  • Insert episode with file_path, quality, size                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: AUTO-MATCH TO TMDB (if no tmdb_id)                                 │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Simple TMDB Search                                                   │  │
│  │  Search: "Be My Princess" → TMDB ID: 133953 ✓                        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                    AI SERIES MATCHER (--finder / --finder-all)              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: POSTER ANALYSIS                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                      gpt-5-nano (Vision)                              │  │
│  │                                                                       │  │
│  │  📷 Input: poster_url → Download → Base64 encode                     │  │
│  │                                                                       │  │
│  │  📊 Extract:                                                          │  │
│  │  ├── is_indian: true/false                                           │  │
│  │  ├── country_origin: India/Korea/China/etc                           │  │
│  │  ├── actors_on_poster: ["name1", "name2"]                            │  │
│  │  ├── directors_on_poster: ["name1"]                                  │  │
│  │  ├── networks: ["Netflix", "Disney+"]                                │  │
│  │  ├── production_companies: ["company1"]                              │  │
│  │  ├── tmdb_id: 295241 (if known)                                      │  │
│  │  └── imdb_id: "tt37356230" (if known)                                │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                          │                                                  │
│              ┌───────────┴───────────┐                                      │
│              ▼                       ▼                                      │
│     ┌────────────────┐      ┌────────────────┐                             │
│     │ IDs FOUND?     │      │ NO IDs         │                             │
│     │ Skip to Step 3 │      │ Continue ↓     │                             │
│     └────────────────┘      └────────────────┘                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: TMDB SEARCH WITH CONTEXT                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Search TMDB API with:                                                │  │
│  │  ├── Clean series name                                               │  │
│  │  ├── Year (if available)                                             │  │
│  │  └── Country filter from poster                                      │  │
│  │                                                                       │  │
│  │  If multiple results → gpt-5-nano selects best match                 │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                          │                                                  │
│              ┌───────────┴───────────┐                                      │
│              ▼                       ▼                                      │
│     ┌────────────────┐      ┌────────────────┐                             │
│     │ MATCH FOUND ✓  │      │ NO MATCH ✗     │                             │
│     │ Go to Step 3   │      │ Try Fallback ↓ │                             │
│     └────────────────┘      └────────────────┘                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 2b: FALLBACK - GPT-5.2 DIRECT ID LOOKUP                               │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                      gpt-5.2 (Vision)                                 │  │
│  │                                                                       │  │
│  │  📷 Input: Same poster image                                         │  │
│  │                                                                       │  │
│  │  🎯 Task: "Identify this series and provide TMDB/IMDb IDs"           │  │
│  │                                                                       │  │
│  │  📊 Output:                                                           │  │
│  │  {                                                                    │  │
│  │    "series_name": "AIR: All India Rankers",                          │  │
│  │    "tmdb_id": 295241,                                                │  │
│  │    "imdb_id": "tt37356230",                                          │  │
│  │    "confidence": "medium"                                            │  │
│  │  }                                                                    │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                          │                                                  │
│              ┌───────────┴───────────┐                                      │
│              ▼                       ▼                                      │
│     ┌────────────────┐      ┌────────────────┐                             │
│     │ IDs FOUND ✓    │      │ FAILED ✗       │                             │
│     │ Go to Step 3   │      │ Mark gpt=0     │                             │
│     └────────────────┘      └────────────────┘                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: UPDATE DATABASE                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  UPDATE series SET                                                    │  │
│  │    tmdb_id = 295241,                                                 │  │
│  │    imdb_id = 'tt37356230',                                           │  │
│  │    gpt = 1  -- marked as AI-matched                                  │  │
│  │  WHERE id = 980                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Model Summary

| Model | Purpose | Max Tokens |
|-------|---------|------------|
| gpt-5-nano (Episode) | Episode validation, ambiguous filename parsing | 10000 |
| gpt-5-nano (Poster) | Poster analysis, actor/network extraction, country detection, TMDB/IMDb IDs | 3000 |
| gpt-5.2 (Fallback) | Direct ID lookup when TMDB search fails | 2000 |

## Commands

```bash
# Default: Scan + AI + Import
python3 "Core Application/cli.py" episodes

# Match single series with AI
python3 "Core Application/cli.py" episodes --finder 980

# Match all unmatched series
python3 "Core Application/cli.py" episodes --finder-all

# Simple TMDB matching (no poster analysis)
python3 "Core Application/cli.py" episodes --match-all-series
```

## Flow Summary

1. **Episode Scan** → Regex extracts info → gpt-5-nano validates unclear cases
2. **Import to DB** → Creates series/seasons/episodes tables
3. **TMDB Matching** → Simple search or AI-powered poster analysis
4. **AI Fallback Chain**: gpt-5-nano (fast) → TMDB API → gpt-5.2 (smart)
