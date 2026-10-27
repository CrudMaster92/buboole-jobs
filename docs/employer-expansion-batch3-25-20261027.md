# Enable 25 additional employers — batch 3

Appends 26 exact verified public-source pins for 25 additional employer identities from catalog commit `3ef07e2403794f1b56002398cedb1e08c790d289`. Madysta Canada and USA are two monitors under one employer. All preceding 1,046 pins, collections and exclusions are preserved. There are now 1,072 enabled source pins.

Live tests returned 172 source records. Coverage is explicitly partial, with missing/truncated descriptions on some sources. Madysta has confirmed openings on both Canadian and North Carolina boards.

[Full company list, screening, live evidence and checks](https://github.com/CrudMaster92/buboole-presets/tree/3ef07e2403794f1b56002398cedb1e08c790d289/docs/north-american-expansion-batch3-20261027)

| Employer | Source records |
|---|---:|
| Call Center Guys | 2 |
| Communauté métropolitaine de Montréal | 2 |
| Centre de services scolaire des Hautes-Rivières | 18 |
| Deloupe | 7 |
| Groupe Contant | 10 |
| LJL Mécanique | 8 |
| Groupe Loiselle | 8 |
| Groupe Madysta | 8 |
| Musée McCord Stewart | 2 |
| Mennonite New Life Centre | 1 |
| NTS Amega West Canada | 1 |
| Office Interiors | 1 |
| Pavages Métropolitain | 1 |
| Port de Montréal | 8 |
| Québec International | 1 |
| Ripplecove Hotel & Spa | 10 |
| Robertson College | 10 |
| Ropack Pharma Solutions | 10 |
| Groupe Santé Arbec | 26 |
| Smitty’s Car Wash Canada | 2 |
| SOPFEU | 5 |
| Transcol | 10 |
| Transport Laberge | 10 |
| Transport Hervé Lemieux | 10 |
| XDI Energy Solutions | 1 |

Validated each new pin through `load_monitors` against the actual published catalog checkout: commit, raw-content SHA-256, revision, identity, verification, HTTPS URLs and runtime compatibility. Runtime export check passed (51 files), all 202 collector tests passed, and the catalog passed its 11 tests plus schema/build checks. Existing runtime files are unchanged. Publishing triggers the normal bounded public-feed build.
