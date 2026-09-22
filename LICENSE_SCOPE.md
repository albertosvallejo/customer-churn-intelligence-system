# License Scope

This file clarifies exactly what the MIT License in `LICENSE` covers in this
repository, and what it explicitly does not cover. It follows the layered
licensing policy defined for this portfolio (see
`PLAN_ACCION_HARDENING_PORTFOLIO`, Section 5 — *Frente A: Licencias por
capas*).

## Covered by the MIT License

The MIT License applies to the original source code created by the Project
Author, including:

- application and pipeline code (e.g. `churn_service.py`, API/service layer);
- notebook **code cells** (the executable code itself, not narrative or
  outputs — see "Notebooks" below);
- scripts used to build, train, evaluate, or run the project
  (e.g. `scripts/build_phase7_synthetic_demo_bundle.py` and equivalents);
- test code;
- Dockerfile, Compose files, and other original technical configuration
  written for this project;
- `.py`, `.sql`, `.sh`, and equivalent files created for this project.

## Not covered by the MIT License

Unless expressly stated otherwise, the following are **excluded** from the
MIT License:

- datasets, and any derived or processed data files, in any format
  (including `data/interim/`, `data/processed/` — not published in this
  repository; see "Third-party data" below, and `data/synthetic_demo/`,
  which is original but not source code);
- trained/serialized models and generated artifacts;
- reports, dashboards, figures, and analytical outputs;
- documentation, README content, and narrative/methodology text;
- notebook narrative, markdown cells, and cell outputs (see "Notebooks");
- `STATUS.md` and other operational/status documentation;
- any third-party materials referenced or embedded in the project;
- secrets, credentials, or private configuration (never published;
  excluded from the public repository via `.gitignore`, not licensed).

## Notebooks

Notebooks mix code, narrative, and outputs. The split is:

```markdown
Original source code contained in notebook code cells is licensed under MIT.
Notebook narrative, methodology, figures, outputs and embedded third-party
materials are excluded from the MIT License unless expressly stated otherwise.
```

## Third-party data

This project uses data derived from Kaggle datasets that are **not** owned by
the Project Author and are **not** covered by MIT:

| Dataset | License |
|:--------|:--------|
| `terencicp/e-commerce-dataset-by-olist-as-an-sqlite-database` (source used by this project) | CC BY-NC 4.0 (Attribution-NonCommercial) |
| `olistbr/brazilian-ecommerce` (original Olist dataset on Kaggle) | CC BY-NC-SA 4.0 (Attribution-NonCommercial-ShareAlike) |

Both carry a **NonCommercial** restriction. For that reason, the processed/
derived data artifacts (`data/interim/`, `data/processed/`) are **not
redistributed in this repository**. Readers who want to reproduce the full
pipeline can regenerate them by downloading the public raw SQLite source from
Kaggle and running notebooks 01–09 against it. `data/synthetic_demo/` is
original to this project and does not depend on the Kaggle license, so it is
published as-is.

## Project-specific note

This repository documents a "VivaMarket Brasil" business framing used as a
portfolio-quality analytical storytelling construct; that framing, and the
narrative/methodology built around it, are original content of the Project
Author and are excluded from MIT on the same basis as other documentation
(see "Not covered by the MIT License" above) — they are not code, so MIT does
not apply, but no separate third-party rights are involved either.

## Summary

- **Can reuse under MIT:** the source code listed above.
- **Cannot assume MIT covers:** data, models, reports, documentation,
  methodology, notebook narrative/outputs, or the Kaggle-derived datasets.
- **Third-party rights holders:** Kaggle dataset licensors (Olist / dataset
  republisher), governed by CC BY-NC 4.0 and CC BY-NC-SA 4.0 respectively —
  not the Project Author.

Questions about reuse of anything not covered by MIT should be directed to
the Project Author (see `README.md`, "License & Contact").
