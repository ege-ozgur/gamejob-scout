# Greenhouse fixtures

## Where the shape came from

The structure of these files was derived from a live, public Greenhouse Job Board
response so that the collector is tested against what the API really returns rather
than against what its documentation describes. The two differ: `first_published`
appears on the list endpoint even though the docs list it as single-job only.

Structural details reproduced here on purpose:

- `content` is **HTML-entity-encoded** (`&lt;p&gt;`, and `&amp;amp;` for an ampersand
  that belongs to the company's own text). The `&amp;amp;` matters — it is what makes
  decoding twice visibly different from decoding once.
- `id` and `internal_job_id` are **different integers**, and `id` is the one that
  matches `absolute_url`.
- Timestamps carry a **UTC offset** rather than being UTC already.
- `location` is an object with a `name`, and real locations contain non-ASCII
  characters, so one fixture uses `Kadıköy, İstanbul`.
- `meta.total` sits beside `jobs`, and there is **no pagination**.

## What is invented

**Everything else.** No real company's job text appears in this repository.

The board token is `examplestudio`, the company is "Example Studio", and every title,
description, department, and office is made up. Job IDs are shaped like real ones but
do not refer to any real posting. This matches the convention in `tests/factories.py`:
no real company, careers URL, ATS identifier, or job posting in the test suite.

`absolute_url` deliberately uses `example.com`, which RFC 2606 reserves for exactly this
purpose, rather than the host a real board would name. The collector never requests that
URL — it only validates and stores it — so nothing is lost by keeping it reserved. The one
real host that does appear, in the collector and its tests, is the API endpoint actually
called: `boards-api.greenhouse.io`.

Real job descriptions are the publishing company's copyrighted content, so reproducing
one here to test a parser would be redistribution for no engineering benefit — the
structure is what the collector actually cares about.

The verified real board that informed this shape is recorded in the repository README's
Source coverage table, which is where verification belongs.

## The files

| Fixture | Covers |
| --- | --- |
| `board_two_jobs.json` | Happy path, full field set, entity-encoded content, non-ASCII location |
| `board_empty.json` | A board with no open roles |
| `board_partial.json` | One usable posting beside one with blank `content` |
| `board_bad_id.json` | A usable posting beside one whose `id` is a string |
| `board_unmappable_job.json` | A posting that fails model validation, carrying marker strings that must never reach a warning |
| `board_total_mismatch.json` | `meta.total` disagreeing with the number of jobs returned |
| `board_no_meta.json` | No `meta` at all |
| `board_bad_meta.json` | `meta` present but not an object |
| `board_minimal_fields.json` | No `first_published` and no `location` |
