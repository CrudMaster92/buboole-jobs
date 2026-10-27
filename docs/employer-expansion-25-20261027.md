# Publish 25 screened employer sources

Admits exactly 25 new, live-tested HTTP monitor pins from catalog commit `8a10080c616ff4c8457edcd80786b3aeea87a796` and its `north-american-employers-new-25-20261027` collection. Existing 996 reviewed pins and all exclusions are preserved byte-for-byte as parsed objects. No runtime or lifecycle behavior changes.

The source review, FreeHire directory/alias audit and 267 observed source records are in [the catalog review](https://github.com/CrudMaster92/buboole-presets/tree/8a10080c616ff4c8457edcd80786b3aeea87a796/docs/north-american-expansion-20261027). Leclerc Foods, NanoXplore and Meridian Lightweight Technologies returned both Canadian and US roles. All new sources explicitly declare partial listing coverage. This release does not assert complete descriptions, all employer vacancies or a deduplicated vacancy total.

Validation: 25 exact new monitor pins passed the real runtime and load_monitors hash/identity check; catalog build and 11 catalog tests passed. Public runtime export check and all 202 collector tests passed.
