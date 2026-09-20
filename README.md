# charity-data-tools

Python utilities for enriching UK charity and funder data from three public sources:

- **FTC** — [Find That Charity](https://findthatcharity.uk) REST API (org search, addresses, contact, org type, income)
- **UKG** — [360Giving UK Grantmaking](https://www.threesixtygiving.org/data/ukgrantmaking/) annual dataset (financial data, regulator metadata, geography)
- **UKCAT** — [UK Charity Activity Tags](https://github.com/charity-classification/ukcat) snapshot CSVs (activity classification)

## Installation

```bash
pip install git+ssh://git@github.com/rcvda/charity-data-tools.git
```

Requires Python 3.9+. Dependencies: `requests`, `openpyxl`.

## Modules

### `charity_data_tools.ftc`

FTC API client and data extractors.

```python
from charity_data_tools.ftc.client import FTCClient, orgid_from_url
from charity_data_tools.ftc.extract import extract_address, extract_contact
from charity_data_tools.ftc.helpers import format_date, date_to_fy

import requests
with requests.Session() as session:
    client = FTCClient(session)
    data, err = client.fetch_org("GB-CHC-1234567")
    if not err:
        addr = extract_address(data)
        contact = extract_contact(data)
```

**`FTCClient` methods:**
- `fetch_org(orgid)` — fetch a single org record; returns `(data, err)`
- `search_batch(names)` — batch name search via reconcile API
- `search_all(names)` — search a list, returns classified results per name
- `classify_result(result, query_name)` — `'auto'`/`'review_high'`/`'review_low'`/`'no_match'`
- `alt_names_for(orgid)` — cached alternateName fetch
- `alt_names_match(result, query_name)` — True if query matches any AKA

**Standalone functions:**
- `orgid_from_url(ftc_url)` — extract `GB-CHC-…` token from an FTC URL
- `normalise_for_match(s)` — editorial normaliser for name equivalence

### `charity_data_tools.ukg`

UKG file loader and cell-write helpers.

```python
from charity_data_tools.ukg.loader import load_ukg_index, resolve_source_file
from charity_data_tools.ukg.helpers import norm_charity_num, write_cell, coerce

source = resolve_source_file(sources_dir=Path("data/sources"))
by_charity_num, by_orgid = load_ukg_index(source)
record = by_charity_num.get("1234567")
```

### `charity_data_tools.ukcat`

UKCAT snapshot loader and tag deriver.

```python
from charity_data_tools.ukcat.loader import (
    resolve_source_files, load_taxonomy, load_classifications, derive_tags
)

tax_path, class_paths = resolve_source_files(Path("data/sources"))
taxonomy = load_taxonomy(tax_path)
classifications = load_classifications(class_paths)

codes = classifications.get("GB-CHC-1234567", set())
categories_str, tags_str = derive_tags(codes, taxonomy)
```

## Column mapping

Each project using this library supplies its own thin wrapper script that:
1. Opens its own spreadsheet
2. Calls library functions with the resulting data
3. Writes results back using its own column names

Each consuming project keeps its own wrapper of this kind; the library itself is data-agnostic.

## Data sources

- FTC API: public, no key required. Rate limit: ~0.5 s between calls.
- UKG: download annually from [360Giving](https://www.threesixtygiving.org/data/ukgrantmaking/). CC BY 4.0.
- UKCAT: download snapshots from [charity-classification/ukcat](https://github.com/charity-classification/ukcat/tree/main/data). CC BY 4.0.

## Licence

MIT

### `charity_data_tools.ch`

Companies House Public Data API client — Stage 4 of the identity cascade, for
the ordinary private companies FTC does not hold.

```python
from charity_data_tools.ch import CHClient
with CHClient() as ch:                      # key from env, or CHClient(api_key=...)
    matches = ch.search_companies("Ryder Architects")
```

#### Providing a Companies House key

This is a **public repository — never commit a key.** The client takes the key
by injection or environment:

- pass `CHClient(api_key="…")`, or
- set `COMPANIES_HOUSE_API_KEY` in your environment (a local `.env` — gitignored
  — or a CI secret). Copy `.env.example` to `.env` to start.

Missing key raises `CHKeyMissing` with guidance. The key is used only as HTTPS
Basic-auth and is never logged. Free key: https://developer.company-information.service.gov.uk/

### `charity_data_tools.identity`

Generalised organisation identity resolution cascade (Stages 1/3/4 + identifier
harvest) — resolve any list of organisation names to canonical org-ids.

```python
from charity_data_tools.ftc.client import FTCClient
from charity_data_tools.ch import CHClient
from charity_data_tools.identity import resolve_names, write_review_csv

with FTCClient() as ftc, CHClient() as ch:
    results = resolve_names(["Anglo American", "Tree Council"], ftc, ch=ch)
write_review_csv(results, "org_id_review.csv")   # propose → grade → confirm
```

Stage 2 (bulk type-register pulls) is deferred pending confirmation of FTC's
`/orgid/type/{slug}` export endpoint (see the cascade spec).
