# BF / BHF document archive

Bajaj Finance and Bajaj Housing Finance annual reports, investor presentations and conference call transcripts.

- [Document index](catalog/INDEX.md)
- [Coverage and unresolved gaps](catalog/COVERAGE.md)
- [Source URLs, download results and SHA-256 hashes](catalog/manifest.json)
- [Collection runs](https://github.com/adeeparora/BF-BHF/actions/workflows/collect-documents.yml)

Documents are organised under `BF/` and `BHF/`, each with `annual-reports/`, `presentations/` and `concall-transcripts/`. Distinct issuer and exchange filing versions are retained; byte-identical files are deduplicated.

Sources: issuer investor-relations pages, publicly linked documents indexed by Screener, BSE/NSE filings, and historical issuer PDFs found through web search. Screener was cross-checked using the owner's signed-in browser; credentials are not stored or used by the downloader.

Some historical links are unavailable. The coverage file states the obtained range and unresolved gaps; this archive does not claim complete lifetime coverage. Collection can be rerun manually through GitHub Actions; no recurring schedule is enabled.
