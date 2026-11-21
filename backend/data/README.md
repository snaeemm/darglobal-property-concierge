# Data (not included)

The corpus and listing snapshots are not redistributed here: they come from DarGlobal's public site and from Wasalt's public sitemaps and Internet Archive snapshots, and belong to their owners.

Rebuild them with the scripts in `../../scraper/`:

1. `parse_wasalt_sitemaps.py` → `wasalt_listings.json`, `wasalt_markets.json`
2. `fetch_wasalt_archive.py` → listing details
3. `build_corpus.py` → `knowledge.json`, `listings.json`, `stats.json`

Respect each site's `robots.txt` and terms. Owner names, phone numbers and other personal data are dropped before indexing.
