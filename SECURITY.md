# SECURITY

## Security policy for the public release line

This document records the public secret-handling and operator-key policy of the project.

## Core rule: BYOK only for LLM-capable functions

The project does **not** ship a shared hidden OpenAI key for operator-side AI features.

What is allowed:

- public synthetic dashboard without a key;
- local `.env` files with the operator's own key;
- server-side LLM execution only when the operator explicitly enables it.

What is not allowed:

- committing a real `.env` into Git;
- placing the real key in `.env.example`;
- embedding the key in frontend code or browser-delivered assets;
- silently using fallback project-owner credentials for public release claims.

## Runtime variables and meaning

From `.env.example`:

- `LLM_MODE=disabled` by default
- `OPENAI_API_KEY=` empty by default
- `OPENAI_MODEL=` empty by default
- `PHASE7_REVIEW_TOKEN` required for protected review routes

This means the documented default release posture is:

- dashboard usable without a key;
- LLM features off by default;
- operator must opt in and provide their own key.

## Review-token policy

Protected review routes are guarded by the Phase 7 review token.

Current hardened behavior evidenced in tests and audits:

- protected routes must reject missing or invalid auth;
- the preferred contract is the `X-Phase7-Token` header.

## Secret storage policy

### Allowed

- `.env` outside Git
- operator-managed key insertion for live LLM paths

### Disallowed

- committing `.env`
- storing the real key in `.env.example`
- writing the key into README examples beyond a placeholder
- exposing the key through browser traffic or static bundles

## Verified with evidence

- public synthetic dashboard works without a key (`CP2`, `CP3`, `CP5` evidence)
- BYOK posture is documented and preserved server-side (`03_cp3_fastapi_byok_audit.md`)
- protected operator routes enforce token gating
- the public CI workflow includes secret scan + tests + smoke validation for the repo contract

## Explicitly outside this public release

- staging, systemd, or Drive-specific secret handling;
- production cutover secrets;
- hidden project-owner credentials.

## Practical operator checklist

1. Copy `.env.example` to `.env`.
2. Leave `LLM_MODE=disabled` unless a live LLM check is intentionally required.
3. If enabling live LLM behavior, set your own `OPENAI_API_KEY` only in `.env`.
4. Never paste the key into the browser.
5. Never commit `.env`.
6. Use `X-Phase7-Token` for protected review pages and writes.
