# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Data archive and interactive dashboard for ACH (Association for Computers and the Humanities) conference presentations. Sourced from the [Index of DH Conferences](https://dh-abstracts.library.virginia.edu/) at the University of Virginia Library.

## Key Commands

```bash
# Build the data pipeline (generates ach_data.json from relational CSVs)
python3 build_data.py

# Serve the dashboard locally
python3 -m http.server 8000
# Then open http://localhost:8000/dashboard.html

# Install dependencies (only needed for keyword generation)
pip3 install openai
```

## Architecture

### Data Pipeline (`build_data.py`)
Joins 22 relational CSVs from `dh_full/dh_conferences_data/` into `ach_data.json`. Steps:
1. Loads all CSV tables, filters to ACH conference series (series ID `2`)
2. Joins works → authorships → affiliations → institutions → countries
3. Merges existing keywords from the database
4. For works without keywords, calls OpenAI GPT-5.2 API (batches of 50, JSON mode, temperature 0.3)
5. Caches API results in `generated_keywords_cache.json` to avoid re-calling
6. Outputs `ach_data.json` with records sorted by year

Reads API key from `.env` file (format: `OPENAI_API_KEY=sk-...`).

### Dashboard (`dashboard.html`)
Single-file HTML app using D3.js v7 and TopoJSON. Features:
- Sticky filter bar: year range slider, organizer dropdown, type dropdown, keyword search
- Charts: timeline, top 20 keywords (clickable), top 20 institutions, world map, keyword trends
- Searchable/sortable/paginated data table
- All charts rebuild reactively on filter change

Uses safe DOM manipulation (createElement/textContent) — no innerHTML with dynamic content.

### Data Files
- `ach_data.json` — Pre-processed dashboard data (~1 MB, 2,711 records)
- `ACH_Conference_Presentations.xlsx` — Excel export with per-presenter rows (4,770 rows)
- `generated_keywords_cache.json` — Cached GPT-5.2 keyword results (gitignored)

## Data Structure

### Normalized relational CSVs (`dh_full/dh_conferences_data/`)
22 CSV tables. Key join paths:

```
works → authorships → authors → appellations (names)
authorships → authorship_affiliation → affiliations → institutions → countries
works → works_keywords → keywords
works.parent_session → works (panel/session grouping)
works.conference → conferences → conference_series_membership → conference_series
conferences → conference_organizer → organizers
```

**Important**: Countries table uses `pref_name` (not `name`) for country names. IDs are string-typed across all CSVs. Set `csv.field_size_limit(sys.maxsize)` — some fields contain full-text abstracts.

## ACH Conference Scope

The ACH/ICCH conference series (series ID `2`) spans three eras:
- **1973–1987**: ACH solo (all US locations)
- **1989–2006**: Joint ACH/ALLC (alternated US/Europe/Canada)
- **2019–2022**: ACH renewed biennial (Pittsburgh, then Virtual)

Coverage gaps: 2021 (indexed, 0 works entered), 2023–2024 (behind ConfTool registration walls).

## Adding Missing Conference Years

When data for 2021, 2023, or 2024 becomes available:
1. If from UVA database: re-download the full relational dump and replace `dh_full/`
2. If from other sources: add works to the CSVs following the existing schema
3. Run `python3 build_data.py` — it will generate keywords for new works automatically (uses cache for previously processed works)
4. Dashboard picks up changes from the regenerated `ach_data.json`

## Data Source

- Simple CSV: `https://dh-abstracts.library.virginia.edu/downloads/dh_conferences_works.csv`
- Full relational dump: `https://dh-abstracts.library.virginia.edu/downloads/public`
