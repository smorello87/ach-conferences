# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Data archive and interactive dashboard for ACH (Association for Computers and the Humanities) conference presentations (1973–2024, ~2,980 records). Deployed via GitHub Pages.

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

# Install Python dependencies (only for keyword generation)
pip3 install openai openpyxl
```

Keyword generation requires `.env` file with `OPENAI_API_KEY=sk-...`. Without it, the pipeline runs but skips keyword generation for uncached works.

## Architecture

Two-stage data pipeline feeding a single-file frontend:

```
UVA relational CSVs ──► build_data.py ──┐
                                        ├──► ach_data.json ──► dashboard.html
ConfTool XLSX/XLS ──► ingest_conftool.py┘
```

### Data Pipeline

**`build_data.py`** — Main pipeline. Joins 22 relational CSVs from `dh_full/dh_conferences_data/`, filters to ACH series (series ID `2`), generates keywords via OpenAI GPT-5.2 (batches of 50, JSON mode, temperature 0.3), then imports ConfTool records via `ingest_conftool.load_conftool_records()`. Outputs `ach_data.json`.

**`ingest_conftool.py`** — Parses ACH 2023 (`.xlsx` via openpyxl) and 2024 (`.xls` XML SpreadsheetML via stdlib `xml.etree.ElementTree`). Handles:
- Filtering: rejects `acceptance_status == -1`, `[CANCELLED]` sessions
- Type mapping: `ACCEPTANCE_TYPE_MAP` dict maps ConfTool acceptance values → existing type strings
- Institution/country extraction from `authors_formatted_N_organisation` columns (up to 14 authors), with `COUNTRY_ALIASES` normalization and `sa_country` fallback
- Panel title cleaning: strips `#2B:` prefixes and `(Lightning Talks)` suffixes
- Keyword generation: same GPT-5.2 approach but includes author-provided keywords as context

Both scripts share `generated_keywords_cache.json` — keys are work IDs (numeric for UVA, `ct2023-*`/`ct2024-*` for ConfTool).

### Dashboard (`dashboard.html`)

Single-file HTML app (~900 lines) using D3.js v7 and TopoJSON. Year slider range, subtitle text, and stats are set dynamically from `DATA.meta` on load. All charts rebuild reactively via `applyFilters()` → `renderAll()`.

Uses safe DOM manipulation (createElement/textContent) — no innerHTML with dynamic content.

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

## ACH Conference Scope

The ACH/ICCH conference series (series ID `2`) spans:
- **1973–1987**: ACH solo (US locations)
- **1989–2006**: Joint ACH/ALLC (US/Europe/Canada)
- **2019–2024**: ACH renewed biennial (Pittsburgh, Virtual, Houston, Fairfax)

Coverage gap: 2021 (indexed in UVA database, 0 works entered).

## Adding Future Conference Years

1. If from UVA database: replace `dh_full/` with new relational dump
2. If from ConfTool: add the export file, update `ingest_conftool.py` with new file path/year/city, add any new acceptance values to `ACCEPTANCE_TYPE_MAP`
3. Run `python3 build_data.py` — uses cache for previously processed works
4. Dashboard picks up changes automatically from regenerated `ach_data.json`

## Data Sources

- **UVA Index of DH Conferences** (covers 1973–2006, 2019, 2022): https://dh-abstracts.library.virginia.edu/
  - Full relational dump: https://dh-abstracts.library.virginia.edu/downloads/public
  - Simple CSV: https://dh-abstracts.library.virginia.edu/downloads/dh_conferences_works.csv
- **ConfTool exports** (covers ACH 2023 Houston, 2024 Fairfax): exported XLSX/XLS files in repo, parsed by `ingest_conftool.py`

Data source attribution is displayed in the dashboard footer.
