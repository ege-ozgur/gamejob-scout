# Lever fixtures

## Where the shape came from

The structure of these files was derived from a live, public Lever Postings API response,
so the collector is tested against what the API really returns rather than against what its
documentation describes. The two differ in several places: `createdAt` is present although
undocumented, `categories.department` is documented but absent, and `workplaceType` uses
`onsite` rather than the documented `on-site`.

Structural details reproduced here on purpose:

- The top level is a **bare JSON array**. There is no envelope and no `meta`, so there is
  no count to check the payload against.
- `description` is **real HTML**, not entity-encoded. This is the opposite of Greenhouse,
  and the reason nothing is unescaped in the Lever collector.
- `lists[].content` holds **bare `<li>` items with no `<ul>` wrapper**, and that content is
  **not** part of `description`. One fixture, `board_only_lists.json`, reproduces the case
  seen on every posting of the live board, where the requirements exist *only* in `lists` —
  taking `description` alone would silently discard them.
- A list's `content` contains `&amp;`, which belongs to the company's own text. It must
  survive untouched, proving no unescaping is applied.
- `id` is an opaque string. The live board happened to use UUIDs, but the documentation
  promises only "a unique posting ID", so `board_opaque_ids.json` covers valid non-UUID
  forms as well.
- `createdAt` is present and is epoch milliseconds. It is **not mapped to anything** —
  Lever publishes no publication timestamp, and a creation time is not one.

## What is invented

**Everything else.** No real company's job text appears in this repository.

The site token is `examplestudio`, the company is "Example Studio", and every title,
description, list, and team is made up. Posting IDs are shaped like real ones but refer to
nothing. This matches the convention in `tests/factories.py`: no real company, careers URL,
ATS identifier, or job posting in the test suite.

`hostedUrl` deliberately uses `example.com`, which RFC 2606 reserves for exactly this
purpose, rather than the `jobs.lever.co` host a real posting would name. The collector never
requests that URL — it only validates and stores it — so nothing is lost. The one real host
that appears, in the collector and its tests, is the endpoint actually called:
`api.lever.co`.

That distinction matters here more than it did for Greenhouse: `jobs.lever.co/robots.txt`
disallows a list of AI crawlers, while `api.lever.co/robots.txt` allows everything with
`Crawl-delay: 1`. We only ever talk to the API.

Real job descriptions are the publishing company's copyrighted content, so reproducing one
here to test a parser would be redistribution for no engineering benefit — the structure is
what the collector actually cares about.

## The files

| Fixture | Covers |
| --- | --- |
| `board_two_postings.json` | Happy path, full field set, lists, `additional`, `createdAt` |
| `board_empty.json` | A board with no open roles |
| `board_only_lists.json` | Content exists **only** in `lists` — the live board's real case |
| `board_no_lists.json` | `description` only, empty `lists` |
| `board_partial.json` | One usable posting beside one with a blank `text` |
| `board_opaque_ids.json` | Valid non-UUID IDs: numeric, mixed-case with an underscore, single character |
| `board_blank_description.json` | Every description field blank, so nothing can be composed |
| `board_unmappable.json` | A posting failing model validation, carrying marker strings that must never reach a warning |

## Why pagination has no fixtures

A "full page" is `LEVER_PAGE_SIZE` postings. Committing a 100-entry JSON file — several
times over, for each pagination scenario — would be unreadable and would obscure the one
thing each case is actually about: how many entries a page holds and which IDs are on it.

Pagination payloads are therefore generated inside `test_lever.py`, where a page's size and
contents are visible on the same screen as the assertion about them.
