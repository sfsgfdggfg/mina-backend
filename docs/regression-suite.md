# Controlled Pilot Regression Suite

The canonical pre-merge regression gate is an explicit, ordered set in
`src/simulation/pilot_regression_suite.py`. It covers the privacy and access
boundaries, safe launcher/API entry, extraction confirmation, trusted customer
identity, provenance and recovery, pilot scope, durable and atomic state,
supplier RFQ lifecycle and repositories, authenticated manual-send evidence,
supplier response ingestion, operator client, regulatory controls, supplier
eligibility/pricing, operational data validation/health, and the current quote
approval and quote case contracts.

The gate runs in-process with temporary/in-memory test state. It does not parse
the live AI email scenarios and does not require `OPENAI_API_KEY`, SMTP, HTTP
providers, portal access, or internet access. Membership is intentionally not
discovered from filenames.

## Non-canonical and retired coverage

`python -m src.main` remains the legacy development/AI simulation suite. It is
not a pilot release gate: after its local evaluator phase it parses the AI email
cases and therefore requires configured live AI behavior.

The following evaluators remain as historical code but are retired from the
canonical gate:

- `evaluate_quote_case_workflow_persistence`: assumes `process_shipment`
  creates a quote case before supplier responses; current workflow creates it
  only during resumed quote progression.
- `evaluate_quote_case_api_contract`: replaces the parser with a `Shipment`
  and bypasses the required extraction proposal and human-confirmation step.
- `evaluate_quote_send_safety_regression`: its old aggregate fixture lacks the
  authenticated operator and decision-timestamp evidence now required. Current
  approval workflow, repository, service, and API regressions retain the active
  approval safety assertions.
- `evaluate_final_quote_consistency_block` and
  `evaluate_supplier_response_required_state`: patch the removed synchronous
  supplier-response simulator on `process_shipment`; the current supplier RFQ
  lifecycle and response-ingestion suites cover these safety outcomes.

Legacy data-health/registry checks, simulated mail-delivery checks, quote-send
preparation checks, and AI email scenarios are not the controlled-pilot gate.
They may still be useful during broader development, but must not be treated as
proof that the current pilot architecture is regression-clean.
