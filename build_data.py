#!/usr/bin/env python3
"""Build ach_data.json from relational CSVs + OpenAI keyword generation."""

import csv, sys, json, os, time
csv.field_size_limit(sys.maxsize)

# Load .env file if present
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

BASE = "dh_full/dh_conferences_data"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
KEYWORD_CACHE = "generated_keywords_cache.json"

def load_csv(name):
    rows = {}
    with open(f"{BASE}/{name}.csv", "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["id"]] = row
    return rows

print("Loading tables...")
appellations = load_csv("appellations")
institutions = load_csv("institutions")
affiliations = load_csv("affiliations")
conferences = load_csv("conferences")
work_types = load_csv("work_types")
keywords_table = load_csv("keywords")
countries_table = load_csv("countries")
organizers_table = load_csv("organizers")

# Conference -> organizer mappings
conf_orgs = {}
with open(f"{BASE}/conference_organizer.csv", "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        conf_orgs.setdefault(row["conference"], []).append(row["organizer"])

conf_org_str = {}
for cid, org_ids in conf_orgs.items():
    names = [organizers_table.get(oid, {}).get("abbreviation", "") for oid in org_ids]
    conf_org_str[cid] = "; ".join(n for n in names if n)

# ACH conference IDs (series 2)
ach_conf_ids = set()
with open(f"{BASE}/conference_series_membership.csv", "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["series"] == "2":
            ach_conf_ids.add(row["conference"])

# Load ACH works
works = {}
with open(f"{BASE}/works.csv", "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["conference"] in ach_conf_ids:
            works[row["id"]] = row
print(f"ACH works: {len(works)}")

# Authorship affiliations
auth_aff = {}
with open(f"{BASE}/authorship_affiliation.csv", "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        auth_aff.setdefault(row["authorship"], []).append(row["affiliation"])

# Authorships
authorships_by_work = {}
with open(f"{BASE}/authorships.csv", "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["work"] in works:
            authorships_by_work.setdefault(row["work"], []).append(row)

# Existing keywords
work_keywords = {}
with open(f"{BASE}/works_keywords.csv", "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["work"] in works:
            kw = keywords_table.get(row["keyword"], {}).get("title", "")
            if kw:
                work_keywords.setdefault(row["work"], []).append(kw)

# ---- Generate missing keywords via OpenAI ----
works_needing_kw = [wid for wid in works if wid not in work_keywords]
print(f"Works needing keyword generation: {len(works_needing_kw)}")

# Load cache
kw_cache = {}
if os.path.exists(KEYWORD_CACHE):
    with open(KEYWORD_CACHE, "r") as f:
        kw_cache = json.load(f)
    print(f"Loaded {len(kw_cache)} cached keyword results")

uncached = [wid for wid in works_needing_kw if wid not in kw_cache]
print(f"Uncached works to process: {len(uncached)}")

if uncached and OPENAI_API_KEY:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    # Build batches of 50
    batches = []
    for i in range(0, len(uncached), 50):
        batch = uncached[i:i+50]
        batches.append(batch)

    print(f"Processing {len(batches)} batches...")
    for bi, batch in enumerate(batches):
        titles_block = ""
        for wid in batch:
            w = works[wid]
            parent_title = ""
            ps = w.get("parent_session", "")
            if ps and ps in works:
                parent_title = f" [Panel: {works[ps]['title']}]"
            titles_block += f"ID:{wid} | {w['title']}{parent_title}\n"

        prompt = f"""For each academic presentation below, generate 2-4 topical keywords that describe the subject matter.
Keywords should be lowercase, concise (1-3 words each), and focus on the research topic (e.g., "text encoding", "machine learning", "medieval manuscripts", "corpus linguistics").

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
            print(f"  Batch {bi+1}/{len(batches)}: {len(result)} results")
        except Exception as e:
            print(f"  Batch {bi+1}/{len(batches)} ERROR: {e}")
            time.sleep(2)

        if (bi + 1) % 5 == 0:
            with open(KEYWORD_CACHE, "w") as f:
                json.dump(kw_cache, f)

    # Final save
    with open(KEYWORD_CACHE, "w") as f:
        json.dump(kw_cache, f)
    print(f"Saved {len(kw_cache)} keyword results to cache")

elif uncached:
    print("WARNING: No OPENAI_API_KEY set. Skipping keyword generation.")

# Merge generated keywords
for wid in works_needing_kw:
    if wid in kw_cache:
        work_keywords[wid] = kw_cache[wid]

print(f"Total works with keywords after generation: {len(work_keywords)}")

# ---- Build output records ----
records = []
for wid, w in works.items():
    conf = conferences.get(w["conference"], {})
    wt = work_types.get(w["work_type"], {})
    is_parent = wt.get("is_parent", "False") == "True"

    parent_title = ""
    ps = w.get("parent_session", "")
    if ps and ps in works:
        parent_title = works[ps]["title"]

    kws = work_keywords.get(wid, [])

    # Get institutions for this work
    inst_set = []
    inst_countries = []
    auths = authorships_by_work.get(wid, [])
    for a in auths:
        for aff_id in auth_aff.get(a["id"], []):
            aff = affiliations.get(aff_id, {})
            inst = institutions.get(aff.get("institution", ""), {})
            iname = inst.get("name", "")
            if iname and iname not in inst_set:
                inst_set.append(iname)
                c = countries_table.get(inst.get("country", ""), {})
                cname = c.get("pref_name", "")
                if cname and cname not in inst_countries:
                    inst_countries.append(cname)

    year = conf.get("year", "")
    records.append({
        "id": wid,
        "year": int(year) if year.isdigit() else 0,
        "conference": conf.get("label", ""),
        "organizers": conf_org_str.get(w["conference"], ""),
        "title": w["title"],
        "panel": parent_title,
        "type": wt.get("title", ""),
        "is_parent": is_parent,
        "keywords": kws,
        "institutions": inst_set,
        "countries": inst_countries,
    })

# Merge ConfTool records (ACH 2023, 2024)
from ingest_conftool import load_conftool_records
conftool_records = load_conftool_records()
records.extend(conftool_records)

records.sort(key=lambda r: (r["year"], r["title"].lower()))

# Build summary metadata
year_set = sorted(set(r["year"] for r in records if r["year"] > 0))
all_keywords = {}
all_institutions = {}
all_countries = {}
for r in records:
    for kw in r["keywords"]:
        all_keywords[kw] = all_keywords.get(kw, 0) + 1
    for inst in r["institutions"]:
        all_institutions[inst] = all_institutions.get(inst, 0) + 1
    for c in r["countries"]:
        all_countries[c] = all_countries.get(c, 0) + 1

output = {
    "meta": {
        "total_works": len(records),
        "year_range": [year_set[0], year_set[-1]] if year_set else [0, 0],
        "years": year_set,
        "source": "Index of DH Conferences, University of Virginia Library",
        "url": "https://dh-abstracts.library.virginia.edu/",
        "generated": time.strftime("%Y-%m-%d"),
    },
    "records": records,
}

outpath = "ach_data.json"
with open(outpath, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False)

print(f"\nSaved {len(records)} records to {outpath}")
print(f"File size: {os.path.getsize(outpath) / 1024 / 1024:.1f} MB")
print(f"Unique keywords: {len(all_keywords)}")
print(f"Unique institutions: {len(all_institutions)}")
print(f"Unique countries: {len(all_countries)}")
