# Repair publication budget

Push-triggered releases collect for five minutes; scheduled and manual runs retain forty minutes. Both load every reviewed source pin, restore durable public state, apply the same source status and expiry rules, and publish the full merged feed. This does not use the isolated `--monitor` smoke option. Revised source revisions are already prioritized by the canonical collector. Unreached sources keep their actual freshness and remain queued for later collection; a release is not a claim that every source has just been refreshed.

The Ubuntu browser setup uses the main HTTPS archive mirror after the Azure mirror stalled for ten minutes in the isolated smoke workflow. The verified smoke mirror setup completed successfully.

Validation: runtime export integrity and all 175 feed tests remain unchanged and passed before this workflow-only adjustment. Review confirms the event selects only literal 5 or 40 minute values and changes no source pins, publication state lease, credentials, review gates or output contracts.
