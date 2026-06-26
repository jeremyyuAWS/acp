# Classify test files

Five compliant HTML docs **named** to exercise the Classify-tab classifier. Document
**type** comes from the real extension; **department** and exposure **tags** are
inferred from filename keywords (`classifyByName` in `frontend/src/ontology.js`).
Scan these and the Classify tab spreads across departments + exposure instead of a
flat "internal · Unassigned".

| File | Department | Exposure tag |
|------|-----------|--------------|
| `HR-benefits-welcome-guide.html` | Human Resources | high-traffic |
| `Marketing-public-landing-page.html` | Marketing | public-facing |
| `Legal-contract-retention-hold.html` | Legal & Compliance | legal-hold |
| `Finance-Q3-budget-summary.html` | Finance | — (internal) |
| `Operations-safety-evacuation-procedure.html` | Operations | — (internal) |

**Note:** type is real; department/exposure are filename **heuristics** (honest demo
classification). PII is tagged from real detection when Deep scan is on. To classify
your own docs, name them with a department keyword (hr, legal, finance, marketing,
ops, clinical) and/or an exposure keyword (public, legal/hold, faq/help/guide).
