# DATASET SOURCE CHECKSUM — CANONICAL RECORD

## Scope

This document defines the **official expected checksum** for the source dataset used by the notebook chain NB01→NB09.

It exists so reproducibility checks do not depend on an ad hoc recalculation with no project-level canonical reference.

## Canonical dataset file

- **Logical dataset name:** Olist / VivaMarket SQLite source database
- **Repository path:** `data/raw/churn_sqlite_db.sqlite`
- **Upstream reference recorded in project:** `data/raw/churn_sqlite_db_source.txt`
- **Source URL recorded in project:** `https://www.kaggle.com/datasets/terencicp/e-commerce-dataset-by-olist-as-an-sqlite-database`

## Official expected checksum

- **Algorithm:** SHA-256
- **Official expected SHA-256:** `0b12d638703b8265a404032ceef38af1e9f810c800c7576600d0c0ad676ddb90`
- **Recorded file size:** `112730112` bytes
- **Canonicalization date:** `2026-08-14`
- **Canonicalization basis:** direct checksum computed on the repository source file present at `data/raw/churn_sqlite_db.sqlite` and adopted as the project’s official expected baseline after the Phase 7 determinism closure.

## Verification procedure

Run from the project root:

```bash
sha256sum data/raw/churn_sqlite_db.sqlite
python3 - <<'PY'
from pathlib import Path
p = Path('data/raw/churn_sqlite_db.sqlite')
print(p.stat().st_size)
PY
```

Expected result:

```text
0b12d638703b8265a404032ceef38af1e9f810c800c7576600d0c0ad676ddb90  data/raw/churn_sqlite_db.sqlite
112730112
```

## Interpretation rules

- If the checksum matches, the notebook chain is reading the canonical source dataset expected by this repository.
- If the checksum differs, the dataset must be treated as a different source baseline until the discrepancy is explained and explicitly accepted.
- A matching filename without a matching checksum is **not** sufficient evidence.

## Evidence captured when this document was created

Verification command output used for this canonical record:

```text
0b12d638703b8265a404032ceef38af1e9f810c800c7576600d0c0ad676ddb90  data/raw/churn_sqlite_db.sqlite
bytes= 112730112
```

## Change policy

This checksum should change only if the project intentionally adopts a different canonical source dataset. If that happens, update this document, record the reason in `_private/_docs/tech_doc.md`, and treat the change as a reproducibility event rather than a silent refresh.
