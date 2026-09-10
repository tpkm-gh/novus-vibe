# Fund Screen PDF Copilot — Playbook

**Prototype built for a forward-deployed-engineer conversation at NovusMinds
AI.** Not affiliated with NovusMinds — built independently from
NovusMinds' based on public descriptions as *"AI workflow and
compliance automation for RIAs, TAMPs, and private banks."* Sources for
every external claim in this document (Adobe API behavior, free-tier
limits) are listed in the Appendix.

This document is written the way I'd want a new engineer — or an
interviewer — to be able to pick this up cold: what problem it solves, why
it's built this way, what's deliberately not built yet, and how to extend
it. It follows the shape of the assignment: **discovery → design → build →
operate → limitations → scaling.**

---

## 1. Discovery: from business requirement to use case

### The raw ask

> Screen funds and generate PDF documents based off a webpage, using the
> Adobe PDF API; store the documents temporarily in Adobe's cloud storage;
> provide a retrieval option.

### Why this is a good FDE showcase

An FDE at a company selling "AI workflow and compliance automation" for
RIAs and private banks spends most of their time on exactly this shape of
problem: an advisor or ops team has *a page of information that needs to
become a durable, retrievable, auditable artifact* — a fund screen result,
a model portfolio snapshot, a disclosure page — and the client wants that
to happen without someone manually printing-to-PDF and filing it by hand.
That's a real, narrow, defensible wedge into a much bigger workflow-
automation story, which is what this prototype tries to demonstrate: not
"a chatbot that talks about funds," but a small, operable pipeline with a
system of record, retries, and self-checking, that a real ops team could
depend on.

### Requirements extraction

Turning the one-paragraph ask into something buildable meant answering
questions a real discovery conversation with a client would surface. Since
there's no live client here, each is answered with an explicit, named
assumption rather than silently picked:

| Question a real discovery call would ask | Assumption made here |
|---|---|
| What counts as "a fund to screen" — a single fund page, or a listing/results page? | A **listing/results page** (a fund screener's output), since that's the more realistic advisor workflow: "here are the 15 funds that matched my client's screen, snapshot this." |
| Does the advisor need the *rendered* page (what a browser shows) or the *underlying data* (structured fund records)? | The **rendered page** — Adobe PDF Services' HTML-to-PDF-from-URL operation captures a visual snapshot, not structured data extraction. If the real requirement is structured data, this is the wrong tool (see §8, Limitations). |
| How long does a generated PDF need to stay retrievable — days, or years (compliance retention)? | Treated as **indefinite / compliance-grade**, meaning the app persists its own copy rather than depending on Adobe's storage (see Decision #2 below) — but no actual retention *policy* (auto-delete after N years, legal hold) is implemented. |
| Who else needs to see a generated document — just the requesting advisor, or a compliance team too? | **Single-tenant, no user model** in this prototype — every request is visible to everyone who can reach the dashboard. Named explicitly in §8; real usage needs auth and per-firm isolation before it touches a second client's data. |
| What should happen when the source page is broken, paywalled, or returns garbage? | This is the one substantive engineering answer this prototype actually gives, not just assumes: **the DocGen agent reflects on its own output and flags or retries rather than silently handing back a bad document.** See §3 and §4. |

---

## 2. Architecture overview

```
                    ┌─────────────────────────┐
   advisor  ──POST──▶  FastAPI (app/main.py)  │
   (browser)          └─────────┬──────┬──────┘
                                 │      │
                     ┌───────────┘      └───────────┐
                     ▼                               ▼
          ┌────────────────────┐          ┌──────────────────────┐
          │   DocGen Agent      │          │  Controller Agent     │
          │  (app/agents/       │          │  (app/agents/         │
          │   docgen_agent.py)  │          │   controller_agent.py)│
          │                      │          │                       │
          │  plan → act →        │          │  read-only:           │
          │  observe → reflect → │          │  list / detail / stats│
          │  retry-or-finish      │          │  view-models for the  │
          └─────────┬────────────┘          │  dashboard             │
                     │                       └───────────┬───────────┘
        ┌────────────┼────────────┐                      │
        ▼            ▼             ▼                      │
  ┌───────────┐ ┌───────────┐ ┌───────────────┐           │
  │ url_      │ │ PDF        │ │ Reflection     │           │
  │ validation│ │ Provider   │ │ Provider       │           │
  │ (SSRF-lite│ │ mock|live  │ │ rule_based|llm │           │
  │  guard)   │ │ (Adobe)    │ │                │           │
  └───────────┘ └───────────┘ └───────────────┘           │
                     │                                      │
                     ▼                                      ▼
              stored PDF file                    ┌────────────────────┐
              (storage/*.pdf)  ◀──────────────────┤ Postgres (or SQLite)│
                                writes/reads       │ screen_requests table│
                                                    └────────────────────┘
```

**Request lifecycle (state machine):** `pending → in_progress → {succeeded
| needs_review | failed}`. `needs_review` and `failed` are both terminal —
neither auto-retries indefinitely; both are distinguishable outcomes an
operator dashboard can filter on, which is the entire point of having more
than a boolean `ok` field.

### Why only one of the two agents "reasons"

The assignment asked for two agents — one that talks to Adobe, one that
serves the dashboard. It would have been easy to make both of them
"agentic" for the sake of the label, but that's not how I'd design it for a
real client, and it's not how I designed it here:

- **DocGen agent** genuinely runs a ReAct-style loop: it plans (validate
  the URL before spending a call), acts (calls a tool — the PDF provider),
  observes the result, reflects on whether that result is acceptable, and
  decides whether to act again. That loop is where judgment is actually
  needed, because the input (an arbitrary webpage) is unpredictable.
- **Controller agent** is deliberately *not* agentic. It reads rows a
  human or the DocGen agent already wrote and reshapes them for the UI.
  There is no judgment call in "does this request exist, what's its
  status" — making that step reason with a model would add latency, cost,
  and a new failure mode for zero benefit. An interviewer asking "why
  isn't your dashboard agent smarter" should get this answer: *agentic
  where the input is unpredictable, deterministic where it isn't* — the
  same split WealthOS's own rules-engine-vs-writeup design uses, applied
  to a different problem.

---

## 3. The DocGen agent's loop, in detail

```python
# app/agents/docgen_agent.py, simplified
validate_source_url(url)                       # PLAN — reject before any provider call
for attempt in 1..max_retries+1:
    outcome = provider.generate(url, attempt)   # ACT
    reflection = reflector.review(outcome)      # OBSERVE + REFLECT
    if reflection.verdict == PASS:              # DECIDE
        persist(); mark SUCCEEDED; stop
    elif reflection.verdict == NEEDS_REVIEW:
        persist(); mark NEEDS_REVIEW; stop        # flag for a human, don't guess
    elif reflection.verdict == FAIL and attempts remain:
        continue                                   # retry
    else:
        mark FAILED; stop
```

`TransientProviderError` (retry-worthy: timeout, rate limit) and
`PermanentProviderError` (not retry-worthy: bad URL, quota exhausted, bad
credentials) are distinguished at the provider layer, so the agent doesn't
waste retries on something that will never succeed.

**`NEEDS_REVIEW` never auto-retries.** A thin or blank-looking PDF from a
given URL will very likely look exactly the same on a second try — the
problem is upstream (page didn't render, screen returned nothing), not
transient. Auto-retrying it would just burn Adobe API quota for the same
answer; flagging it for a human is the honest response, and it's the same
"human sign-off gate" principle the WealthOS prototype named as its
next-most-important missing piece.

---

## 4. Decisions worth defending

**1. Content-aware reflection, not byte-size heuristics.**
The rule-based reflector extracts text from the generated PDF (via
`pypdf`) and measures *character count*, not file size. Byte size is
dominated by font embedding and PDF structural overhead far more than by
visible content — two structurally valid PDFs with wildly different amounts
of real content can land at nearly the same size. This was caught during
development, not by inspection: an early byte-size-based threshold flagged
a legitimate 16-fund listing as "thin" because PDF overhead ate the margin
I'd budgeted for content. Switching to extracted-character count fixed it
and is the more defensible signal to explain to a regulator asking "how do
you know a document is complete."

**2. Our own persisted copy is the system of record — never Adobe's asset
URL.** Adobe's PDF Services docs don't publish a retention SLA for
generated assets, and the SDK's cloud-asset handle isn't meaningfully
re-resolvable from a bare ID string outside the job's original process.
So `local_pdf_path` (a file the app wrote itself the moment the job
finished) is what every retrieval reads from; `adobe_asset_id` is kept only
as an audit-trail breadcrumb. `retrieve()` on both providers reflects this
honestly — `AdobeMockProvider.retrieve()` and `AdobeLiveProvider.retrieve()`
both return `None` unconditionally, forcing every code path onto the
locally persisted file rather than pretending a second copy exists
somewhere it might not.

**3. Provider abstraction on both axes (PDF generation *and* reflection) —
same pattern, deliberately reused.** `mock`/`live` for Adobe, `rule_based`/
`llm` for reflection. Both default to the option that needs zero
credentials and zero network. This is the single decision that makes the
whole prototype interview-safe: a flaky venue wifi, an expired trial
credential, or a rate limit can't take the demo down, because the default
path never depends on any of those. It's the same call the WealthOS
prototype made for its write-up step, applied here to two different seams.

**4. The LLM reflection layer can only *downgrade*, never *upgrade*, a
verdict.** `LLMReflectionProvider` always runs the deterministic structural
check first; the model only gets a turn if that check already passed, and
its only power is to flip `PASS → NEEDS_REVIEW` (e.g., "this rendered fine
but doesn't look like fund data — looks like a login wall"). It cannot
override a structural `FAIL`, and it cannot manufacture a `PASS` on
something that failed to parse as a PDF at all. If the LLM call errors or
times out, the code falls back to the structural verdict rather than
failing the request — a flaky critique should never be why a generation job
is lost.

**5. URL validation blocks the obvious SSRF cases, and says so.**
`url_validation.py` requires `https://` and rejects literal private/
loopback/link-local IPs, mirroring Adobe's own documented constraint for
this operation. It does **not** re-resolve DNS at request time, so it
won't catch DNS rebinding (a hostname that resolves publicly at validation
time and privately at fetch time). Named as a limitation in §8, not
silently left out.

**6. Requests run synchronously, on purpose, for this prototype.**
`POST /api/screen-requests` blocks until the DocGen agent's loop finishes
(typically well under a second against the mock provider; a real Adobe
call plus polling could take several seconds). That's the right call for a
same-day demo — you watch the status change in the response you already
have — and the wrong call for production, which is why it's the first
thing in §9.

---

## 5. Data model

One table, `screen_requests` (`app/models.py`) — every field exists because
some part of the pipeline reads or writes it:

| Field | Purpose |
|---|---|
| `id` | `REQ-xxxxxxxx`, generated at creation |
| `label`, `source_url` | What the advisor asked for |
| `status` | `pending / in_progress / succeeded / needs_review / failed` |
| `provider_name`, `adobe_asset_id`, `adobe_job_location` | Audit trail of what actually called Adobe |
| `local_pdf_path`, `file_size_bytes`, `page_count` | Our own persisted copy — the retrieval system of record (Decision #2) |
| `reflection_verdict`, `reflection_notes` | What the reflection step concluded, and why |
| `retry_count`, `attempt_log` (JSON) | Full plan/act/observe/reflect trace for that request |
| `error_message`, `latency_ms` | Operator-facing diagnostics |
| `requested_at`, `completed_at` | Timestamps |

The schema deliberately avoids Postgres-only types (`UUID`, `JSONB` —
plain `String`/`JSON` instead) so the identical model runs against both
Postgres and the SQLite fallback used for zero-setup demos and fast unit
tests. That's a scope cut named here, not hidden: a production schema
serving only Postgres could use native `UUID`/`JSONB` and gain a bit of
type safety and indexing flexibility back.

---

## 6. Build & operate

### Running it

Two paths, both real (both actually exercised during development, not just
documented):

- **SQLite fallback** (`USE_SQLITE_FALLBACK=1`, the `.env.example`
  default) — zero infrastructure, `uvicorn app.main:app` and go.
- **Postgres** (`docker-compose.yml` ships a `postgres:16` service) — the
  production-shaped path. **Verified against a real local PostgreSQL 16
  instance during development** (not just asserted): the full pipeline —
  create → generate → reflect → retrieve, plus the API test suite — was
  run against `postgresql+psycopg://...@localhost:5432/novus_vibe` and
  passes identically to the SQLite path.

### Environment variables (`.env.example`)

| Variable | Default | Notes |
|---|---|---|
| `USE_SQLITE_FALLBACK` | `1` | `0` to use `DATABASE_URL` (Postgres) instead |
| `DATABASE_URL` | — | Postgres connection string |
| `PDF_PROVIDER` | `mock` | `live` to call real Adobe PDF Services |
| `PDF_SERVICES_CLIENT_ID` / `_SECRET` | — | Only needed when `PDF_PROVIDER=live` |
| `REFLECTION_PROVIDER` | `rule_based` | `llm` to add an Anthropic critique pass |
| `ANTHROPIC_API_KEY` | — | Only needed when `REFLECTION_PROVIDER=llm` |
| `MAX_GENERATION_RETRIES` | `2` | Attempts beyond the first before giving up |

### Flipping on the live Adobe path

Adobe's free developer tier: **500 document transactions/month**, ongoing
(not a time-limited trial), no card required. Get credentials at Adobe's
[PDF Services getting-started page](https://developer.adobe.com/document-services/docs/overview/pdf-services-api/gettingstarted/),
set `PDF_PROVIDER=live` plus the client ID/secret, done — no code change.

**Before relying on this in front of an interviewer:** `app/agents/
providers/adobe_live.py` is written against the module layout and class
names Adobe documents and ships in its own `pdfservices-python-sdk-samples`
repo as of September 2026 (sources in the Appendix). Adobe has changed this
SDK's package layout across major versions before, so run:

```bash
python -c "from adobe.pdfservices.operation.pdfjobs.jobs.html_to_pdf_job import HTMLToPDFJob"
```

If that import fails, the installed SDK's layout has moved — fix the
import lines at the top of `adobe_live.py`'s `generate()` method; nothing
else in that file needs to change.

### GitHub

Code lives at `tpkm-gh/novus-vibe`. Single-branch (`main`), no CI pipeline
configured yet — see §9 for what a real one would run.

---

## 7. Testing & evaluation

32 tests, four layers:

1. **`test_repository.py`** — CRUD + stats math against an isolated
   in-memory SQLite session per test.
2. **`test_docgen_agent.py`** — the reflect/retry loop, one behavior per
   test (happy path, transient-then-recover, permanent fail-fast, thin
   content flagged, invalid URL rejected pre-provider, SSRF-literal
   rejected, retrieval).
3. **`test_controller_agent.py`** — view-model shaping.
4. **`test_api.py`** — through the real FastAPI app (routing, DI, response
   schemas), against the app's actual DB wiring.
5. **`test_eval_scenarios.py`** — the eval harness: one table asserting
   every terminal outcome the agent can reach, in one place, so the
   *range* of behavior is visible to a reviewer rather than scattered:

| Scenario | Expected outcome |
|---|---|
| Clean listing | `succeeded` / `pass`, 0 retries |
| Transient timeout | `succeeded` / `pass`, 1 retry — recovers |
| Permanent provider error (bad host) | `failed` fast, 0 retries — no wasted attempts |
| Thin/blank content | `needs_review` — flagged, not silently passed *or* blindly retried |
| Non-HTTPS URL | `failed` at the PLAN step, before any provider call |

A test asserts this table stays in sync with `RequestStatus` itself
(`test_scenario_table_covers_every_terminal_status`), so a new status value
added later can't silently fall outside eval coverage.

**Why the eval harness stays on the deterministic mock + rule-based
reflection, even with an LLM key available:** the same reason the WealthOS
prototype's eval suite ran offline — assertions on exact verdicts need
reproducibility a live model's sampling can't give you. `LLMReflectionProvider`
is a real, usable upgrade for a live demo's qualitative judgment; it is
deliberately not what the eval suite is graded against.

```bash
pytest -q                          # SQLite-backed unit/API tests, ~1s
DATABASE_URL=... USE_SQLITE_FALLBACK=0 pytest tests/test_api.py -q   # against real Postgres
```

---

## 8. Assumptions, limitations & restrictions

Named on purpose, not discovered by an interviewer poking at the code.

**Assumptions** (see §1's table for the full discovery reasoning):
- Input is a public, unauthenticated, HTTPS fund-listing/screener page —
  not one behind a login or paywall.
- "Screen funds" means *capture the page as it renders*, not extract
  structured per-fund data.
- Long-term retrieval is a compliance-grade requirement, so the app
  persists its own file rather than trusting Adobe's storage — but no
  actual retention/deletion *policy* is implemented.
- Single tenant, no distinction between requesters.

**Limitations, named rather than hidden:**
- **No auth, no SSO, no per-firm data isolation.** Anyone who can reach
  the dashboard sees every request. The first thing to add before this
  touches a second client's data.
- **Synchronous request handling.** One HTTP request blocks for the full
  duration of generation + reflection; no queue, no worker pool, no way to
  submit a batch of 50 URLs and walk away. See §9.
- **SSRF protection is scheme + literal-IP only** — no DNS re-resolution
  at fetch time, so DNS rebinding isn't caught (Decision #5).
- **No rate-limit or quota-exhaustion handling beyond a generic permanent
  failure.** Adobe's 500-transaction/month free-tier ceiling isn't tracked
  proactively — the app finds out the same way the advisor would, by the
  next call failing.
- **The live Adobe SDK integration is written from documentation, not
  exercised against a real Adobe account** (no credentials available while
  building this) — flagged explicitly in §6 with the exact command to
  verify before a live demo.
- **No idempotency/locking around concurrent processing of the same
  request** — fine for one FastAPI worker process (this prototype's
  target), not safe if naively scaled to multiple worker processes without
  the queue-based redesign in §9.
- **This is a two-step reflect/retry loop, not a general-purpose
  autonomous agent framework.** It does not do open-ended multi-tool
  planning (e.g., an agent deciding *which* of several tools to call, or
  chaining unrelated tools together). That scope was intentional — see §1.

---

## 9. Scaling & future-proofing

In priority order, the way I'd sequence it with a real team:

1. **Move generation off the request thread.** Queue (`arq`, Celery, or
   even Postgres-as-queue via `SELECT ... FOR UPDATE SKIP LOCKED`) +
   worker pool; `POST` returns `202` immediately with a request ID, the
   dashboard polls or gets pushed a status update. This also fixes the
   concurrency/idempotency gap in §8 — workers claim a row, not a request
   handler racing another request handler.
2. **Auth + per-firm data isolation.** SSO (the same OAuth patterns Adobe
   itself uses) before a second client's data ever touches this.
3. **Observability.** Structured logging and metrics per pipeline stage
   (this prototype's `attempt_log` JSON column is the seed of that —
   in production it becomes real spans, not a JSON blob), plus alerting on
   `needs_review`/`failed` rate crossing a threshold.
4. **Human sign-off UI for `needs_review`.** The dashboard currently shows
   the flag; it doesn't yet let a human approve/override/re-run with
   different params from the UI. That loop is implied, not built.
5. **Proactive Adobe quota tracking**, so the app degrades gracefully
   (queue and warn) before the 500th call of the month fails outright.
6. **Containerize + deploy** (Dockerfile, health checks, secrets manager
   instead of `.env`) once this leaves "prototype on a laptop."
7. **If the tool surface grows** — e.g., adding a second document source
   beyond "webpage URL," or letting the agent decide *which* generation
   strategy to use — that's the point to move DocGen off a hand-rolled
   loop and onto a framework like LangGraph, which is worth the added
   dependency once there's real multi-path branching to manage. Not worth
   it at today's one-tool scope.

---

## 10. How this maps to the FDE role

An FDE showing up at a client doesn't get a clean spec — they get "we need
to screen funds and file the results," and the job is discovery
(§1), a design that a compliance-minded client will actually trust
(§2–§4, especially the "don't silently guess, flag it" pattern in §3),
something that runs today with zero infrastructure risk to the demo
(§6's provider-abstraction pattern), and an honest account of what's not
done yet (§8) with a real sequenced plan for what's next (§9) — not a
slide that says "production-ready."

---

## Appendix: sources

- Adobe PDF Services — Create PDF how-to: <https://developer.adobe.com/document-services/docs/overview/pdf-services-api/howtos/create-pdf>
- Adobe PDF Services — HTML to PDF: <https://developer.adobe.com/document-services/apis/pdf-services/html-to-pdf/>
- Adobe PDF Services — getting started / auth: <https://developer.adobe.com/document-services/docs/overview/pdf-services-api/gettingstarted/>
- Adobe PDF Services — licensing & usage limits (500 free transactions/month): <https://developer.adobe.com/document-services/docs/overview/limits>
- `pdfservices-sdk` on PyPI: <https://pypi.org/project/pdfservices-sdk/>
- Adobe's own Python SDK sample for this exact operation: <https://github.com/adobe/pdfservices-python-sdk-samples/blob/main/src/htmltopdf/html_to_pdf_from_url.py>
- NovusMinds company page (industries served, positioning): <https://novusminds.ai/company/>
