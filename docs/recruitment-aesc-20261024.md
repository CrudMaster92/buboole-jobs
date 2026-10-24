# Recruitment internal-employment source admission

Depends on catalog commit `9eac0a0c7d0d93130fff20cee01eb9ed1aa8e6f8` and its recruitment expansion PR.

Adds eight exact reviewed pins: CHG Healthcare, Talentful, Egon Zehnder, Onward Search, Sheffield Haworth, Ingenovis Health SThree and Stone Harbor Staffing Group (formerly Epic Staffing Group). Existing source pins, exclusions and collector implementation are preserved. Their canonical live validations returned 220 distinct source postings in total; bounded listing flags and enrichment warnings are retained in the recipes/evidence. Employbridge and Express headquarters are provider-backed catalog additions and have no native feed pin.

Evidence: `docs/recruitment-aesc-20261024.md`, `docs/recruitment-aesc-20261024-validation.json` and the full 207-entry AESC comparison in the pinned catalog commit. This is internal agency employment, not a client-placement import. All eight recipes use public HTTPS hosts with no credentials or private state. Source observations are point-in-time counts, not lasting coverage guarantees.

The generated-runtime export check passed and all 193 feed tests passed before this lock-only update. A separate local public collector smoke run uses these reviewed pins, empty independent state and a temporary output directory. Never replace production state with that filtered smoke snapshot.

Do not merge until the catalog source has been approved and merged. After approved deployment, verify the live feed generation and each added source status/company coverage; a PR and a local smoke build do not establish live publication.

Public smoke validation: the first seven sources produced a validated independent 216-posting generation (108 descriptions). The rebranded Stone Harbor source is validated separately, with explicit partial coverage because advertised totals varied. Temporary smoke outputs remain outside this repository and are not production state.
