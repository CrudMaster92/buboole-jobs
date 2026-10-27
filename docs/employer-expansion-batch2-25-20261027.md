# Admit 25 more screened employer sources

Adds exactly 25 new HTTP source pins from catalog commit `46e983f03c40601398167737c8a823dff90aeedb` and the `north-american-employers-new-25-batch2-20261027` collection. All 1,021 preceding source pins and every exclusion are preserved. Runtime and lifecycle code are unchanged.

The [catalog review](https://github.com/CrudMaster92/buboole-presets/tree/46e983f03c40601398167737c8a823dff90aeedb/docs/north-american-expansion-batch2-20261027) includes the 25-company list, current FreeHire directory/alias screening, profile disambiguation, and live results: 216 observed source records. This is Canadian employer coverage, not a claim of 25 companies hiring in both countries or a deduplicated vacancy count. All sources declare partial listing coverage.

Validation: catalog schema/build checks, 11 catalog tests, public runtime export check and 202 public collector tests passed. The 25 new published source pins are checked against their exact monitor bytes and identities before activation.
