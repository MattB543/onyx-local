# Email-to-CRM: why the two futureoflife.org emails likely never processed (2026-06-11)

Two emails (from `taylor@futureoflife.org` and `websites@futureoflife.org`) were sent to the
CRM mailbox ~1h before this diagnosis and never appeared in Irving (the FLI instance).

## Most likely root cause

**`EMAIL_CRM_CUSTOM_JOB_ID` is not set on the Irving deployment.**

The local `.env` notes file (repo root, FLI block) records the Irving instance with:

```
ENABLE_CUSTOM_JOBS=true
EMAIL_CRM_CUSTOM_JOB_ID=          <-- blank
```

In `backend/onyx/indexing/adapters/document_indexing_adapter.py` (`post_index()`, ~line 341),
trigger-event emission is wrapped in:

```python
custom_job_id = _get_email_crm_custom_job_uuid()
if custom_job_id is not None:
    self._emit_email_crm_trigger_events(...)
```

When the env var is unset this silently skips emission — the email gets indexed as a document,
but **no `custom_job_trigger_event` row is ever created**, so the CRM workflow never fires and
nothing is logged. (As of today a WARNING log was added for exactly this case.)

Note: `VALID_EMAIL_DOMAINS` is NOT the cause — the emission path intentionally does not filter
by sender domain (see comment at `document_indexing_adapter.py:377-382`); the domain list is
only injected into the CRM prompt to mark internal teammates.

## Other silent drop points (in pipeline order)

1. **Job id unset / invalid UUID** — emission skipped (above). *Now logged as WARNING.*
2. **Email not (re)indexed** — if the IMAP connector didn't run or the doc wasn't in
   `updatable_docs`, nothing emits. Check connector status / index attempts in admin UI.
3. **Dedupe suppression** — IMAP dedupe key is stable (`imap:{doc.id}`); a previously-emitted
   message never re-emits. Was logged at DEBUG; *now INFO*.
4. **Job disabled** — `claim_trigger_events_for_runs()` only claims events for jobs with
   `enabled = true`; events sit in `RECEIVED` forever. *Now logged.*
5. **Concurrency limits** — `max_concurrent_runs` / `max_events_per_claim` skip claiming
   silently. *Now logged.*
6. **Run failure** — missing/invalid `persona_id` in step config, persona lacking CRM tools, or
   chat-pipeline errors mark the run `FAILURE` and the event `FAILED` (with `error_message`).
   Visible in the new CRM "Email Queue" tab.

## How to verify on the Irving box

SSH to 18.117.171.2 timed out from this machine (instance IP may have changed or port 22 is
closed), so these need to be run from a machine that can reach it:

```bash
# 1. Is the env var set in the containers?
docker exec onyx-background-1 env | grep -E 'EMAIL_CRM_CUSTOM_JOB_ID|ENABLE_CUSTOM_JOBS|VALID_EMAIL'

# 2. Were trigger events created for the two emails?
docker exec onyx-relational_db-1 psql -U postgres -c \
  "SELECT id, status, created_at, error_message, payload_json->>'from' AS from_email, payload_json->>'subject' AS subject
   FROM custom_job_trigger_event
   WHERE payload_json->>'from' ILIKE '%futureoflife.org%'
   ORDER BY created_at DESC LIMIT 20;"

# 3. Event/run status breakdown
docker exec onyx-relational_db-1 psql -U postgres -c \
  "SELECT status, count(*) FROM custom_job_trigger_event GROUP BY status;"
docker exec onyx-relational_db-1 psql -U postgres -c \
  "SELECT r.status, r.error_message, r.created_at FROM custom_job_run r ORDER BY r.created_at DESC LIMIT 10;"

# 4. Does the custom job exist and is it enabled?
docker exec onyx-relational_db-1 psql -U postgres -c \
  "SELECT id, name, enabled, trigger_type FROM custom_job;"

# 5. Did the IMAP connector even index the emails?
#    Admin UI -> Connectors -> IMAP -> recent index attempts / doc count.
```

Interpretation:
- Query 2 returns 0 rows and env var blank → root cause confirmed: create the custom job
  (POST /api/admin/custom-jobs/) and set `EMAIL_CRM_CUSTOM_JOB_ID`, then restart backend
  services. Re-deliver/re-index the emails (IMAP dedupe is keyed on doc id, so a brand-new
  re-send is the simplest way to trigger processing).
- Events exist with status `RECEIVED` → job disabled or claim loop not running
  (`ENABLE_CUSTOM_JOBS`, beat worker).
- Events `FAILED` → read `error_message` (persona misconfig is the usual suspect) — now also
  visible in the CRM "Email Queue" tab.
