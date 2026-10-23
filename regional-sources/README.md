# Reviewed regional public observations

Super C's official Metro listing limits non-Canadian visitors. These anonymous
posting observations were collected normally on a Canadian host through the
canonical public runtime. They contain public vacancies only and need the same
source review as a catalog pin update.

Refresh from a permitted regional host, using this checkout's reviewed lock and
its exact catalog checkout:

```sh
python -m server.public_jobs regional-snapshot --catalog .catalog --lock catalog-lock.json --monitor super-c --monitor super-c-lachute --output regional-sources
```

Review and publish the resulting JSON files. The build imports them with
`--regional-observations regional-sources`. Exact monitor/company/revision/hash
and posting identity checks apply. Observations expire for import after 36 hours;
replaying them never renews source or job freshness, and partial observations do
not establish that unseen roles closed. Missing or expired files fall back to
normal collection, with ordinary seven-day job expiry. No local scheduler is
installed by this change; ongoing coverage needs continued regional collection.

Do not add recruitment profiles, cached search snippets, private application
exports, credentials, browser cookies, or postings that cannot be collected.
