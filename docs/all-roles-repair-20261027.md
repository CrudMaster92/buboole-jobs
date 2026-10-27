# Remove sampling caps from the three employer batches

Replaces exactly 76 source pins covering 75 employers with revision 2 monitors from catalog commit `1aca5890ff9bc879d2ad688f9c3365bd97143137`. All 996 unrelated source pins, all collections, and every exclusion are preserved; enabled source count remains 1,072.

All revised recipes use all-role traversal, null maximum pages, and no description-attempt quota. Folks, Air Inuit and Groupe Lebel traverse page numbers to exhaustion; Preverco uses its full employer listing; WordPress jobs paginate without a total-result cap. Whole-board single-page sources have no sampling limit. Existing ownership exclusions remain in place.

Fresh live runs finished all 76 listing traversals and returned 781 records. Every one of the prior 655 URLs was retained, plus 126 additional URLs. Full descriptions are attempted without a count cap, but source extraction failures remain visible and do not discard valid roles. Interrupted collector work resumes checkpoints rather than claiming completion at a request/time budget.

[Company-by-company evidence and request traces](https://github.com/CrudMaster92/buboole-presets/tree/1aca5890ff9bc879d2ad688f9c3365bd97143137/docs/all-roles-repair-20261027)

Checks passed: 11 catalog tests, 202 collector tests, catalog validation/build, unchanged 51-file runtime export, and loading all 76 published pins against the exact catalog checkout with revision/hash/identity validation. No generated runtime changes.
