# verba-client v0.1.0 -- Review & Remediation Plan

**Review Date:** 2026-02-27
**Reviewers:**
- Katrin Bergsdottir -- Security & Infrastructure Engineer
- Marcus Chen -- API/SDK Design Engineer
- Anya Petrov -- Quality & Reliability Engineer
- Sigrun Thorsdottir -- COO

---

## Review Summary

| Reviewer | Critical | High | Medium | Low | Verdict |
|----------|----------|------|--------|-----|---------|
| Katrin (Security) | 2 | 4 | 7 | 4 | NOT READY |
| Marcus (API Design) | 4 | 6 | 6 | 7 | NOT READY |
| Anya (QA/Reliability) | 3 | 5 | 6 | 5 | NOT READY |
| Sigrun (COO/Business) | -- | -- | -- | -- | CONDITIONAL GO |

**Consensus:** The architecture is sound, but the library needs hardening before
production use or PyPI publication. All four reviewers agree on a common set of
high-priority fixes that can be addressed in 2 phases.

---

## Phase 1: Blockers (Must complete before any deployment)

These items were flagged CRITICAL by 2+ reviewers.

### 1.1 Delete `client.py` from project root
**Flagged by:** Katrin, Marcus, Anya, Sigrun
Old prototype file contains hardcoded plaintext credentials. Delete it,
rotate the credentials, add it to `.gitignore`.
**Effort:** 10 minutes

### 1.2 Remove `python-dotenv` from core dependencies
**Flagged by:** Katrin, Marcus
It's not imported by the library. Move to `dev` optional deps only.
**Effort:** 5 minutes

### 1.3 Wrap `requests.HTTPError` in `VerbaAPIError`
**Flagged by:** Anya (CRITICAL), Marcus (HIGH)
`_request()` calls `raise_for_status()` which throws `requests.HTTPError`
outside the `VerbaAPIError` hierarchy. Consumers catching `VerbaAPIError`
will miss HTTP errors. Also check media error responses for XML error bodies.
**Effort:** 1 hour

### 1.4 Refactor `search_calls()` -- eliminate 40 lines of duplicated logic
**Flagged by:** Marcus (CRITICAL), Anya (HIGH), Katrin (LOW)
Teach `_request()` to accept `list[tuple]` params for repeated keys
(anynum/anyname). Then `search_calls()` can use the standard pipeline
with automatic token-retry.
**Effort:** 2-3 hours

### 1.5 Refactor `put_media()` through `_request()` pipeline
**Flagged by:** Marcus (CRITICAL), Anya (HIGH)
Currently bypasses `_request()` entirely. No token-retry on upload.
Extend `_request()` to support POST with data/body payload.
**Effort:** 1 hour

### 1.6 Add unit tests with mocks (target 80% coverage)
**Flagged by:** Anya (CRITICAL), Marcus (LOW)
Write tests for: XML parsing, error code mapping, token refresh logic,
parameter building, date parsing, `CallRecord.from_xml_element()` edge
cases. Use `responses` library to mock HTTP.
**Effort:** 4-6 hours

---

## Phase 2: Production Hardening & Developer Experience

These items were flagged HIGH by 2+ reviewers and rated MUST-HAVE by the COO.

### 2.1 Enforce HTTPS by default
**Flagged by:** Katrin (CRITICAL)
Validate `base_url` starts with `https://`. Add `allow_insecure=False`
param for explicit HTTP opt-in with a logged warning.
**Effort:** 30 minutes

### 2.2 Add `defusedxml` for XML parsing safety
**Flagged by:** Katrin (HIGH)
Replace `xml.etree.ElementTree` with `defusedxml.ElementTree` to guard
against XXE and billion-laughs attacks.
**Effort:** 15 minutes

### 2.3 Add threading lock for token state
**Flagged by:** Katrin (HIGH), Anya (HIGH)
Wrap `_token`, `_token_acquired_at`, and `_ensure_token()` in a
`threading.Lock`. Document thread-safety stance.
**Effort:** 30 minutes

### 2.4 Add transient failure retry with backoff
**Flagged by:** Katrin (LOW), Marcus (MEDIUM), Anya (HIGH), Sigrun (NICE-TO-HAVE)
Use `urllib3.util.retry.Retry` on the session for 502/503/504 and
connection errors. Make configurable via constructor.
**Effort:** 1 hour

### 2.5 Pagination iterator for large result sets
**Flagged by:** Marcus (HIGH), Sigrun (MUST-HAVE)
Add `search_calls_iter(start, end, page_size=100)` generator that
auto-paginates. Add pagination info to `SearchResult`.
**Effort:** 2-3 hours

### 2.6 Parse `duration` as `timedelta` + add `duration_seconds`
**Flagged by:** Marcus (MEDIUM), Sigrun (MUST-HAVE)
Parse `"HH:MM:SS"` string into `timedelta`. Add `duration_seconds: float`
property. Keep `duration_raw: str` for the original.
**Effort:** 1 hour

### 2.7 Parse `get_voice_quality()` into a dataclass
**Flagged by:** Marcus (HIGH), Sigrun (MUST-HAVE)
Create `VoiceQualityResult` model. Return typed object instead of raw
`ET.Element`.
**Effort:** 1-2 hours

### 2.8 Change boolean params from `int | None` to `bool`
**Flagged by:** Marcus (HIGH)
`return_metadata`, `return_im`, etc. should be `bool` (default `False`).
Convert to `"1"` internally.
**Effort:** 1 hour

### 2.9 Add `Marker` dataclass, replace `list[dict]`
**Flagged by:** Marcus (HIGH)
`get_markers()` should return `list[Marker]` not `list[dict]`.
**Effort:** 30 minutes

### 2.10 Consistent identifier naming (`call_id` everywhere)
**Flagged by:** Marcus (LOW)
Standardize on `call_id` in the public API. Map to `ccdr_id`/`callID`
internally. Add deprecation alias if needed.
**Effort:** 1 hour

### 2.11 Add `CallRecord.to_dict()` and serialization helpers
**Flagged by:** Sigrun (SHOULD-HAVE)
Enable easy export to CSV/Excel/JSON. Optional `to_dataframe()` with
pandas as optional dependency.
**Effort:** 1-2 hours

### 2.12 Add media streaming support
**Flagged by:** Anya (HIGH), Sigrun (SHOULD-HAVE)
Add `get_media_stream()` yielding chunks. Validate Content-Type on
media responses (detect XML error bodies returned as 200).
**Effort:** 1-2 hours

### 2.13 PyPI packaging metadata
**Flagged by:** Marcus (MEDIUM)
Add: `authors`, `readme`, `classifiers`, `[project.urls]`, `py.typed`
marker, `__version__` attribute.
**Effort:** 30 minutes

### 2.14 Add `__repr__` with redacted secrets
**Flagged by:** Katrin (HIGH), Marcus (LOW)
`VerbaClient.__repr__` should show base_url and auth state, not secrets.
**Effort:** 15 minutes

### 2.15 Improve logging: DEBUG-level request/response, fix INFO->DEBUG
**Flagged by:** Anya (MEDIUM)
Log action, status code, elapsed time at DEBUG. Change token-acquired
log from INFO to DEBUG. Use `__name__` for logger.
**Effort:** 30 minutes

---

## Out of Scope (Future Iterations)

- Async client (`AsyncVerbaClient` via `httpx`) -- Sigrun SHOULD-HAVE
- Aggregation convenience methods -- Sigrun SHOULD-HAVE
- Transcript model and access methods -- Sigrun SHOULD-HAVE
- Batch/concurrent operations -- Sigrun NICE-TO-HAVE
- Compliance/retention field exposure -- Sigrun NICE-TO-HAVE

---

## Estimated Timeline

| Phase | Items | Effort | Target |
|-------|-------|--------|--------|
| Phase 1 (Blockers) | 1.1-1.6 | 1-2 days | Before any deployment |
| Phase 2 (Hardening) | 2.1-2.15 | 3-4 days | Before PyPI publish |

---

## Sign-Off

- [ ] **Katrin Bergsdottir** (Security) -- Approves plan addresses all CRITICAL/HIGH security findings
- [ ] **Marcus Chen** (API Design) -- Approves plan addresses SDK consistency and PyPI readiness
- [ ] **Anya Petrov** (QA/Reliability) -- Approves plan addresses test coverage and error handling
- [ ] **Sigrun Thorsdottir** (COO) -- Approves timeline and confirms MUST-HAVE business needs are covered
