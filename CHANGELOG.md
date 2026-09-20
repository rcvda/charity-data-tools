# Changelog

## 0.2.0 (unreleased)
- **Guidance:** for mixed org-type lists, lead with the FTC location-universe match
  (`geo.fetch_location_candidates` + HQ confirmation), not name-reconcile — reconcile
  is charity/company biased and misses GB-EDU/GB-NHS.
- Add `charity_data_tools.identity` — generalised organisation identity
  resolution cascade (Stages 1/3/4 + identifier harvest) promoted from a
  read-only prototype; resolves any list of org names to canonical
  org-ids with a propose/grade/confirm review worksheet.
- Add `charity_data_tools.ch` — Companies House Public Data API client
  (Stage 4). Key is injected or read from `COMPANIES_HOUSE_API_KEY`; never
  stored in the repo.
- Add `ftc.extract.extract_identifiers()` — harvest the full identifier set
  (`orgIDs`/`linked_records`/`charityNumber`/`companyNumber`) from an `/orgid`
  record.
- Companies House matching is suffix-aware (Ltd/Limited/PLC ignored) and low-confidence FTC reconcile noise is discarded, not surfaced.
- Add test suite (HTTP fully mocked; no live key required).
