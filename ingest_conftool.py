#!/usr/bin/env python3
"""Parse ACH 2023/2024 ConfTool exports into records matching build_data.py schema."""

import json, os, re, sys, time
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_2023 = os.path.join(SCRIPT_DIR, "ACH2023Conference_all_contributions_data_papers_2024-01-12_19-42-17.xlsx")
FILE_2024 = os.path.join(SCRIPT_DIR, "ACH2024Conference_papers_2024-11-15_12-57-31.xls")
KEYWORD_CACHE = os.path.join(SCRIPT_DIR, "generated_keywords_cache.json")

# ---- Country normalization ----
COUNTRY_ALIASES = {
    "United States of America": "United States",
    "USA": "United States",
    "US": "United States",
    "U.S.A.": "United States",
    "UK": "United Kingdom",
    "Great Britain": "United Kingdom",
    "Republic of Korea": "South Korea",
    "Korea, Republic of": "South Korea",
    "Korea": "South Korea",
    "Netherlands, The": "Netherlands",
    "The Netherlands": "Netherlands",
    "Czech Republic, The": "Czech Republic",
    "Russian Federation": "Russia",
    "Türkiye": "Turkey",
    "Brasil": "Brazil",
    "People's Republic of China": "China",
    "Peoples Republic of China": "China",
    "P.R. China": "China",
    "Hong Kong": "China",
    "Taiwan, Province of China": "Taiwan",
    "Viet Nam": "Vietnam",
    "Aotearoa New Zealand": "New Zealand",
}

KNOWN_COUNTRIES = {
    "Afghanistan", "Albania", "Algeria", "Argentina", "Armenia", "Australia",
    "Austria", "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados",
    "Belarus", "Belgium", "Belize", "Benin", "Bolivia", "Bosnia and Herzegovina",
    "Botswana", "Brazil", "Brunei", "Bulgaria", "Burkina Faso", "Cameroon",
    "Canada", "Chile", "China", "Colombia", "Costa Rica", "Croatia", "Cuba",
    "Cyprus", "Czech Republic", "Denmark", "Dominican Republic", "Ecuador",
    "Egypt", "El Salvador", "Estonia", "Ethiopia", "Fiji", "Finland", "France",
    "Georgia", "Germany", "Ghana", "Greece", "Guatemala", "Haiti", "Honduras",
    "Hungary", "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland",
    "Israel", "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya",
    "Kuwait", "Kyrgyzstan", "Latvia", "Lebanon", "Libya", "Lithuania",
    "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Mali", "Malta", "Mexico",
    "Moldova", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar",
    "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria",
    "North Macedonia", "Norway", "Oman", "Pakistan", "Palestine", "Panama",
    "Paraguay", "Peru", "Philippines", "Poland", "Portugal", "Qatar", "Romania",
    "Russia", "Rwanda", "Saudi Arabia", "Senegal", "Serbia", "Singapore",
    "Slovakia", "Slovenia", "South Africa", "South Korea", "Spain", "Sri Lanka",
    "Sudan", "Sweden", "Switzerland", "Syria", "Taiwan", "Tanzania", "Thailand",
    "Trinidad and Tobago", "Tunisia", "Turkey", "Uganda", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States", "Uruguay",
    "Uzbekistan", "Venezuela", "Vietnam", "Zambia", "Zimbabwe",
}

# Also recognize raw alias forms as valid countries for extraction
_ALIAS_SOURCES = set(COUNTRY_ALIASES.keys())

# ---- Type mapping ----
ACCEPTANCE_TYPE_MAP = {
    "Accept - Paper": "paper",
    "Accept as Paper": "paper",
    "Accept - Poster": "poster / demo / art installation",
    "Accept as Poster": "poster / demo / art installation",
    "Accept - Lightning": "lightning talk",
    "Accept as Lightning": "lightning talk",
    "Accept as Panel": "panel / roundtable",
    "Accept as Round": "panel / roundtable",
    "Accept - Install": "poster / demo / art installation",
    "ALT format": "panel / roundtable",
}


def normalize_country(name):
    """Normalize a country name to match existing dataset conventions."""
    name = name.strip()
    return COUNTRY_ALIASES.get(name, name)


def extract_institutions_and_countries(org_string):
    """Parse an organisation string like 'University X, Country' into (institutions, countries)."""
    institutions = []
    countries = []
    if not org_string or org_string == "(None)":
        return institutions, countries

    # Split on ;\n or just \n for multi-institution cells
    parts = re.split(r';\n|\n', org_string)
    for part in parts:
        part = part.strip()
        if not part or part == "(None)":
            continue

        # Try to extract trailing country: "Institution Name, Country"
        # Be careful with institutions that have commas in names (e.g., "California State University, Sacramento, United States of America")
        country_found = None
        inst_name = part

        # Check if the last comma-separated segment is a country
        segments = part.rsplit(", ", 1)
        if len(segments) == 2:
            candidate = segments[1].strip()
            normalized = normalize_country(candidate)
            if normalized in KNOWN_COUNTRIES or candidate in _ALIAS_SOURCES:
                country_found = normalized
                inst_name = segments[0].strip()
                # Edge case: "California State University, Sacramento, United States of America"
                # inst_name is now "California State University, Sacramento" which is correct

        if inst_name and inst_name != "(None)" and inst_name not in institutions:
            institutions.append(inst_name)
        if country_found and country_found not in countries:
            countries.append(country_found)

    return institutions, countries


def clean_panel_title(session_title):
    """Clean session title: remove prefix codes and trailing type indicators."""
    if not session_title:
        return ""
    # Remove prefix like "#2B: " or "#13C: "
    title = re.sub(r'^#\d+[A-Za-z]?:\s*', '', session_title)
    # Remove trailing type indicators like "(Lightning Talks)", "(Papers)", "(Poster Session)", "(Panel)", "(Roundtable)"
    title = re.sub(r'\s*\((Lightning Talks|Papers|Poster Session|Panel|Roundtable)\)\s*$', '', title)
    return title.strip()


def parse_keywords_string(kw_string):
    """Split author keywords on commas or semicolons, strip whitespace."""
    if not kw_string:
        return []
    # Split on comma or semicolon
    parts = re.split(r'[;,]', kw_string)
    return [p.strip() for p in parts if p.strip()]


# ---- 2023 XLSX parser ----
def load_2023_rows():
    """Parse the 2023 XLSX file and return filtered, structured rows."""
    import openpyxl
    wb = openpyxl.load_workbook(FILE_2023, read_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()

    headers = [str(h) if h else "" for h in all_rows[0]]

    # Build column index lookup (handle duplicate column names by using first occurrence)
    col_map = {}
    for i, h in enumerate(headers):
        if h and h not in col_map:
            col_map[h] = i

    records = []
    for row in all_rows[1:]:
        def get(name):
            idx = col_map.get(name)
            if idx is None or idx >= len(row):
                return ""
            val = row[idx]
            if val is None:
                return ""
            return str(val).strip()

        # Filter: skip rejected
        acceptance_status = get("acceptance_status")
        try:
            if float(acceptance_status) == -1:
                continue
        except (ValueError, TypeError):
            pass

        acceptance = get("acceptance")
        if acceptance == "Rejected":
            continue

        paper_id = get("paperID")
        title = get("title")
        if not title:
            continue

        # Map type
        work_type = ACCEPTANCE_TYPE_MAP.get(acceptance, "paper")

        # Extract institutions and countries from per-author org columns
        inst_set = []
        country_set = []
        for n in range(1, 15):
            org_col = f"authors_formatted_{n}_organisation"
            org_val = get(org_col)
            if org_val:
                insts, ctrs = extract_institutions_and_countries(org_val)
                for inst in insts:
                    if inst not in inst_set:
                        inst_set.append(inst)
                for c in ctrs:
                    if c not in country_set:
                        country_set.append(c)

        # Fallback: sa_country if no countries found
        if not country_set:
            sa_country = get("sa_country")
            if sa_country:
                c = normalize_country(sa_country)
                if c in KNOWN_COUNTRIES:
                    country_set.append(c)

        # Panel
        panel = clean_panel_title(get("session_title"))

        # Author keywords (raw, for GPT input)
        raw_keywords = parse_keywords_string(get("keywords"))

        records.append({
            "id": f"ct2023-{paper_id}",
            "year": 2023,
            "conference": "2023 - Houston",
            "organizers": "ACH",
            "title": title,
            "panel": panel,
            "type": work_type,
            "is_parent": False,
            "keywords": [],  # filled by keyword generation
            "institutions": inst_set,
            "countries": country_set,
            "_raw_keywords": raw_keywords,
        })

    return records


# ---- 2024 XML SpreadsheetML parser ----
def parse_xml_spreadsheet(filepath):
    """Parse XML SpreadsheetML (.xls) into list of dicts, handling ss:Index gaps."""
    tree = ET.parse(filepath)
    root = tree.getroot()
    ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}

    rows = root.findall('.//ss:Table/ss:Row', ns)
    if not rows:
        return []

    # Parse header row
    header_cells = rows[0].findall('ss:Cell', ns)
    headers = {}
    col_idx = 0
    for cell in header_cells:
        idx_attr = cell.get('{urn:schemas-microsoft-com:office:spreadsheet}Index')
        if idx_attr:
            col_idx = int(idx_attr) - 1
        data_el = cell.find('ss:Data', ns)
        val = data_el.text if data_el is not None and data_el.text else ""
        if val:
            headers[col_idx] = val
        col_idx += 1

    # Build reverse lookup: name -> first column index
    name_to_col = {}
    for ci, name in headers.items():
        if name and name not in name_to_col:
            name_to_col[name] = ci

    # Parse data rows
    result = []
    for row in rows[1:]:
        cells = row.findall('ss:Cell', ns)
        row_data = {}
        ci = 0
        for cell in cells:
            idx_attr = cell.get('{urn:schemas-microsoft-com:office:spreadsheet}Index')
            if idx_attr:
                ci = int(idx_attr) - 1
            data_el = cell.find('ss:Data', ns)
            val = data_el.text if data_el is not None and data_el.text else ""
            col_name = headers.get(ci, "")
            if col_name and ci == name_to_col.get(col_name):
                row_data[col_name] = val.strip()
            ci += 1
        result.append(row_data)

    return result


def load_2024_rows():
    """Parse the 2024 XLS file and return filtered, structured rows."""
    raw_rows = parse_xml_spreadsheet(FILE_2024)

    records = []
    for row in raw_rows:
        def get(name):
            return row.get(name, "").strip()

        # Filter: skip rejected
        acceptance_status = get("acceptance_status")
        try:
            if int(float(acceptance_status)) == -1:
                continue
        except (ValueError, TypeError):
            pass

        acceptance = get("acceptance")
        if acceptance == "Rejected":
            continue

        # Filter: skip cancelled sessions
        session_title = get("session_title")
        if "[CANCELLED]" in session_title:
            continue

        paper_id = get("paperID")
        title = get("title")
        if not title:
            continue

        # Map type
        work_type = ACCEPTANCE_TYPE_MAP.get(acceptance, "paper")

        # Extract institutions and countries from per-author org columns
        inst_set = []
        country_set = []
        for n in range(1, 15):
            org_col = f"authors_formatted_{n}_organisation"
            org_val = get(org_col)
            if org_val:
                insts, ctrs = extract_institutions_and_countries(org_val)
                for inst in insts:
                    if inst not in inst_set:
                        inst_set.append(inst)
                for c in ctrs:
                    if c not in country_set:
                        country_set.append(c)

        # Fallback: sa_country
        if not country_set:
            sa_country = get("sa_country")
            if sa_country:
                c = normalize_country(sa_country)
                if c in KNOWN_COUNTRIES:
                    country_set.append(c)

        # Panel
        panel = clean_panel_title(session_title)

        # Author keywords
        raw_keywords = parse_keywords_string(get("keywords"))

        records.append({
            "id": f"ct2024-{paper_id}",
            "year": 2024,
            "conference": "2024 - Fairfax",
            "organizers": "ACH",
            "title": title,
            "panel": panel,
            "type": work_type,
            "is_parent": False,
            "keywords": [],
            "institutions": inst_set,
            "countries": country_set,
            "_raw_keywords": raw_keywords,
        })

    return records


# ---- Keyword generation via OpenAI ----
def generate_keywords(records, kw_cache):
    """Generate keywords for ConfTool records using GPT-5.2, incorporating author keywords."""
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

    uncached = [r for r in records if r["id"] not in kw_cache]
    print(f"  ConfTool works needing keyword generation: {len(uncached)}")

    if not uncached:
        return

    if not OPENAI_API_KEY:
        print("  WARNING: No OPENAI_API_KEY set. Skipping keyword generation for ConfTool records.")
        return

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    # Build batches of 50
    batches = [uncached[i:i+50] for i in range(0, len(uncached), 50)]
    print(f"  Processing {len(batches)} batches...")

    for bi, batch in enumerate(batches):
        titles_block = ""
        for r in batch:
            author_kws = ", ".join(r["_raw_keywords"]) if r["_raw_keywords"] else ""
            kw_part = f" [Author keywords: {author_kws}]" if author_kws else ""
            titles_block += f"ID:{r['id']} | {r['title']}{kw_part}\n"

        prompt = f"""For each academic presentation below, generate 2-4 topical keywords that describe the subject matter.
Keywords should be lowercase, concise (1-3 words each), and focus on the research topic (e.g., "text encoding", "machine learning", "medieval manuscripts", "corpus linguistics").
Where author-provided keywords are shown, use them as guidance but normalize to lowercase and concise form.

Return ONLY a JSON object mapping each ID to an array of keyword strings. No other text.

Presentations:
{titles_block}"""

        try:
            resp = client.chat.completions.create(
                model="gpt-5.2",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            result = json.loads(resp.choices[0].message.content)
            for wid_key, kws in result.items():
                kw_cache[str(wid_key)] = kws
            print(f"    Batch {bi+1}/{len(batches)}: {len(result)} results")
        except Exception as e:
            print(f"    Batch {bi+1}/{len(batches)} ERROR: {e}")
            time.sleep(2)

        if (bi + 1) % 5 == 0:
            with open(KEYWORD_CACHE, "w") as f:
                json.dump(kw_cache, f)

    # Final save
    with open(KEYWORD_CACHE, "w") as f:
        json.dump(kw_cache, f)
    print(f"  Saved keyword cache ({len(kw_cache)} total entries)")


def load_conftool_records():
    """Main entry point: load, filter, generate keywords, return merged records."""
    # Load .env if present
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    print("\nLoading ConfTool exports...")
    records_2023 = load_2023_rows()
    print(f"  2023 (Houston): {len(records_2023)} accepted records")

    records_2024 = load_2024_rows()
    print(f"  2024 (Fairfax): {len(records_2024)} accepted records")

    all_records = records_2023 + records_2024

    # Load keyword cache
    kw_cache = {}
    if os.path.exists(KEYWORD_CACHE):
        with open(KEYWORD_CACHE, "r") as f:
            kw_cache = json.load(f)

    # Generate keywords
    generate_keywords(all_records, kw_cache)

    # Apply cached keywords and strip internal _raw_keywords field
    for r in all_records:
        r["keywords"] = kw_cache.get(r["id"], [])
        del r["_raw_keywords"]

    print(f"  Total ConfTool records: {len(all_records)}")
    return all_records


if __name__ == "__main__":
    records = load_conftool_records()
    # Print summary
    types = {}
    countries = set()
    for r in records:
        types[r["type"]] = types.get(r["type"], 0) + 1
        countries.update(r["countries"])
    print("\nType distribution:")
    for t, c in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
    print(f"\nUnique countries: {len(countries)}")
    for c in sorted(countries):
        print(f"  {c}")
