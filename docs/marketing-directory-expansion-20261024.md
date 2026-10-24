# Reviewed Marketing Agencies sources

This change adds 12 individually pinned public sources from catalog commit
`4c0d59e3da246cb2504bba4936bc4e36d2bf6661`, proposed in
[catalog PR #48](https://github.com/CrudMaster92/buboole-presets/pull/48).
The existing 925 source pins and 132 exclusions are retained unchanged.
The resulting lock contains 937 sources.

Fresh canonical public-collector observations on 24 October 2026:

| Source | Observed listings | Scope |
| --- | ---: | --- |
| OMD Canada | 9 | Exact OMD agency and Canada country facets |
| PHD Canada | 5 | Exact PHD agency and Canada country facets |
| Initiative | 8 | Exact Initiative agency and Canada country facets |
| UM Canada | 28 | Exact UM agency and Canada country facets |
| McCann | 22 | Exact McCann agency facet |
| AREA 23 | 55 | Exact Area23 agency facet |
| GSD&M | 3 | Exact GSD&M agency facet |
| The Martin Agency | 15 | Exact Martin agency facet |
| Momentum Worldwide | 19 | Exact Momentum agency facet |
| TBWA | 9 | Exact TBWA agency facet; may include future-opportunity postings |
| Cossette | 9 | Exact Cossette brand on shared TalentPoolBuilder board |
| Cossette Media | 17 | Exact Cossette Media brand on shared TalentPoolBuilder board |

These 199 observations are not guarantees of current or complete vacancies.
All new sources explicitly retain partial-listing semantics. Company/country
filters do not establish global completeness, and incomplete sources never
confirm unseen jobs closed. Public collection continues to checkpoint and
enrich descriptions within its existing source budgets. Cossette's bounded
browser listings omit full descriptions; Septième sibling listings are excluded.

The generated runtime includes a canonical Workday identity repair. Newer boards
put job category first in `bulletFields`, with the requisition second. Treating
the first display field as an ID collapsed distinct jobs. The adapter and
traversal now share requisition selection backed by the public posting path,
prefer explicit detail IDs, and fall back to distinct paths when display bullets
cannot be evidenced as identifiers. The export and regression tests are authored
in the canonical application, not independently edited here.

Validation: 198 public-runtime tests; generated export integrity; 70 focused
canonical traversal/mapping tests; canonical web production build; live canonical
public collection of all 12 new sources. Catalog PR #48 passes its remote
validation workflow. Exact pin objects and hashes are checked before publication.
An isolated local publication preview validates all 199 listings; all 26 rendered Cossette application URLs returned HTTP 200.
The 26 FreeHire-only collection additions are provider metadata, not native
collector recipes, and are not copied into this lock.

Merge the catalog change before publishing this feed change. Live feed generation,
source statuses and hosted search projection still require verification after
the approved release; a draft pull request is not a publication receipt.
