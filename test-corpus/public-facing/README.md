# Public-facing test files

Six compliant HTML docs **named** so the Classify tab tags them **public-facing**
(some also **high-traffic**). Upload them to your Drive folder alongside the other
test files and re-scan — the "By exposure & risk" chart will show public-facing > 0.

| File | Exposure tags | Department |
|------|---------------|-----------|
| `public-homepage-www.html` | public-facing, high-traffic | Unassigned |
| `Marketing-press-release-external.html` | public-facing | Marketing |
| `customer-facing-product-brochure.html` | public-facing | Marketing |
| `public-help-center-faq.html` | public-facing, high-traffic | Unassigned |
| `web-landing-campaign.html` | public-facing | Marketing |
| `external-newsletter-public.html` | public-facing | Unassigned |

Classification is filename-driven (`classifyByName` in `frontend/src/ontology.js`):
keywords `public / www / web / landing / press / brochure / external / customer`
→ public-facing; `faq / help / home / guide` → high-traffic.
