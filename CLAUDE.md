# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Data archive and interactive dashboard for ACH (Association for Computers and the Humanities) conference presentations (1973–2026, ~3,140 records). Deployed via GitHub Pages.

Live dashboard: https://smorello87.github.io/ach-conferences/dashboard.html

## Key Commands

```bash
# Build the data pipeline (generates ach_data.json)
python3 build_data.py

# Serve the dashboard locally
python3 -m http.server 8000
# Then open http://localhost:8000/dashboard.html

# Test ConfTool ingestion only (no UVA data)
python3 ingest_conftool.py

# Install Python dependencies
pip3 install openai openpyxl ftfy
```

Keyword generation requires `.env` file with `OPENAI_API_KEY=sk-...`. Without it, the pipeline runs but skips keyword generation for uncached works.

## Architecture

Multi-source data pipeline feeding a single-file frontend:

```
UVA relational CSVs    ──► build_data.py       ──┐
                                                  ├──► ach_data.json ──► dashboard.html
ConfTool XLSX/XLS/CSV  ──► ingest_conftool.py ──┤                       about.html
                                                  │
Web-scraped JSON       ──► ingest_conftool.py ──┘
```

### Data Pipeline

**`build_data.py`** — Main pipeline. Joins 22 relational CSVs from `dh_full/dh_conferences_data/`, filters to ACH series (series ID `2`), generates keywords via OpenAI GPT-5.2 (batches of 50, JSON mode, temperature 0.3), then imports records via `ingest_conftool.load_conftool_records()`. Outputs `ach_data.json`.

**`ingest_conftool.py`** — Parses five data sources:
- ACH 2023 (`.xlsx` via openpyxl)
- ACH 2024 (`.xls` XML SpreadsheetML via stdlib `xml.etree.ElementTree`)
- ACH 2025 (`ach2025_program.json` — scraped from conference website, no institutional affiliations)
- ACH 2026 schedule (`ach2026_program.csv` — ConfTool schedule CSV; ftfy repairs UTF-8-as-cp1252 mojibake; rows with empty Paper Title but a Paper ID become panel-only entries titled by the panel; rows with neither are skipped because their content is supplied by the creative CSV)
- ACH 2026 creative presentations (`ach2026_creative.csv` — 22 entries split across two themed sessions that fill slots 20/21 in the schedule CSV; type `"creative presentation"`; ftfy normalizes curly quotes for consistency)

Handles:
- Filtering: rejects `acceptance_status == -1`, `[CANCELLED]` sessions
- Type mapping: `ACCEPTANCE_TYPE_MAP` dict maps ConfTool acceptance values → existing type strings
- Institution/country extraction from `authors_formatted_N_organisation` columns (up to 14 authors), with `COUNTRY_ALIASES` normalization and `sa_country` fallback
- Panel title cleaning: strips `#2B:` prefixes and `(Lightning Talks)` suffixes
- Keyword generation: same GPT-5.2 approach but includes author-provided keywords as context

Both scripts share `generated_keywords_cache.json` (gitignored) — keys are work IDs (numeric for UVA, `ct2023-*`/`ct2024-*`/`ct2026-*` for ConfTool, `web2025-*` for web-scraped).

### Dashboard (`dashboard.html`)

Single-file HTML app using D3.js v7 and TopoJSON. Features:
- Year range slider, organizer/type/keyword filters with URL hash state (`#ymin=2019&org=ach-only`)
- 7 sections: timeline, keywords, institutions, map, keyword trends, type breakdown (stacked bar), data table
- CSV export of filtered results, shareable filter URLs via "Share View" button
- Chart expand/fullscreen: cards reparent to `document.body` on expand (required for `position: fixed` to work across browsers), restore to original DOM position on collapse. Only the expanded chart re-renders at the larger size via `renderExpandedChart()`.
- Responsive design with breakpoints at 768px and 480px

All charts rebuild reactively via `applyFilters()` → `renderAll()`. Render functions use `chartHeight(container, default)` to detect expanded state and size accordingly. Uses safe DOM manipulation (createElement/textContent) — no innerHTML with dynamic content.

### About Page (`about.html`)

Static page with project context, conference history, and full data source attribution with links. Shares visual styling with the dashboard.

### Output Record Schema

Each record in `ach_data.json`:
```json
{"id", "year", "conference", "organizers", "title", "panel", "type", "is_parent", "keywords": [], "institutions": [], "countries": []}
```
**No author names** — deliberately excluded from output. The `is_parent` field marks session containers (filtered out in dashboard display).

## Data Gotchas

- UVA CSVs: Countries table uses `pref_name` (not `name`). All IDs are string-typed. Must set `csv.field_size_limit(sys.maxsize)` — some fields contain full-text abstracts.
- ConfTool 2024 `.xls`: Not binary XLS — it's XML SpreadsheetML. Cells use `ss:Index` attribute to skip columns; the parser must track column position manually.
- ConfTool files have duplicate column names (e.g., `paperID`, `sa_country` appear twice). Parsers use first occurrence only.
- Organisation strings use `;\n` or `\n` as multi-institution separators, with trailing `, Country Name` pattern for country extraction.
- ACH 2025 web-scraped data has no institutional affiliations — they weren't listed on the conference website.

## ACH Conference Scope

The ACH/ICCH conference series (series ID `2`) spans:
- **1973–1987**: ACH solo (US locations)
- **1989–2006**: Joint ACH/ALLC (US/Europe/Canada)
- **2019–2026**: ACH renewed (Pittsburgh, Virtual, Houston, Fairfax, Virtual, Virtual)

Coverage gap: 2021 (indexed in UVA database, 0 works entered; program locked behind Humanities Commons membership).

## Adding Future Conference Years

1. If from UVA database: replace `dh_full/` with new relational dump
2. If from ConfTool: add the export file (XLSX, XLS-as-XML, or CSV), update `ingest_conftool.py` with new file path/year/city, add any new acceptance values to `ACCEPTANCE_TYPE_MAP`. If the CSV ships with mojibake (UTF-8 decoded as cp1252), wrap cell reads with `ftfy.fix_text()` as in `load_2026_rows()`.
3. If from a conference website: scrape presentations into a JSON file (see `ach2025_program.json` for format), add a loader function in `ingest_conftool.py`
4. Run `python3 build_data.py` — uses cache for previously processed works
5. Dashboard picks up changes automatically from regenerated `ach_data.json`

## Data Sources

- **UVA Index of DH Conferences** (covers 1973–2006, 2019, 2022): https://dh-abstracts.library.virginia.edu/
  - Full relational dump: https://dh-abstracts.library.virginia.edu/downloads/public
  - Simple CSV: https://dh-abstracts.library.virginia.edu/downloads/dh_conferences_works.csv
- **ConfTool exports** (covers ACH 2023 Houston, 2024 Fairfax, 2026 Virtual): exported XLSX/XLS/CSV files in repo, parsed by `ingest_conftool.py`. The 2026 schedule CSV (`ach2026_program.csv`) ships with UTF-8-as-cp1252 mojibake; `ftfy.fix_text()` is applied to every cell on load. A separate CSV (`ach2026_creative.csv`) provides the 22 creative presentations that fill panels 20/21 of the schedule.
- **ACH 2025 web program** (Virtual): scraped from https://ach2025.ach.org/en/program/, stored as `ach2025_program.json`, parsed by `ingest_conftool.py`. No institutional affiliations available.

Data source attribution is displayed on the about page.
