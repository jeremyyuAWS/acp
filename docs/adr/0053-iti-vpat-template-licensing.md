# ADR 0053 — The ITI VPAT® template: what row 13 actually asks for, and the three separable questions behind it

**Status:** Accepted for Q2 (2026-09-07) — the owner decided the reproduction scope. **Q1 remains
open and is still not decided here.** Option C is the one that ships; see *The decision, and what
it does not cover* below.
**Date:** 2026-09-06, amended 2026-09-07
**Related:** `docs/prd-acr-workspace.md` acceptance rows 13 and 14, and the "Phase 5 note".
Code: `api/acr_export_preview.py` (the projection every format is built from),
`api/acr_export_docx.py`, `api/acr_export_pdf.py`, `api/routes/acr.py` (`/preview`,
`/revisions/{n}/export`), `frontend/src/AcrWorkspace.jsx`.
Shipped in: #1484, #1499, #1501, #1509, #1510.

---

## Context

The ACR workspace produces a conformance report about ACP itself. Phase 5's acceptance table has
two rows. Both are answered now; this section is kept as written because the reasoning below is
about how they got there, and the table records where they landed:

| # | Criterion | Status |
|---|---|---|
| 13 | Exported Word document follows the official VPAT structure | ✅ closed 2026-09-07 via **Option C** — structure matched, file not vendored. **Q1 below is still open**, and it is about the NAME, not the structure |
| 14 | Generated Word document passes ACP's accessibility checks | ✅ enforced at the route |

**Row 14 is done and did not depend on row 13**, which is worth stating because the belief that it
did is what left a built, tested export unreachable for some time. The gate applies to whatever
Word document ACP generates; the licence question is about which template the tables sit in.

### What already exists

One projection, four renderers, two lifecycles. `acr_export_preview.project()` produces the report's
content in the VPAT table's *shape* — the same rows, the same column meanings, the same four
conformance terms — and JSON, HTML, PDF and DOCX all render that one projection, for both the live
draft (`/preview`) and a published revision (`/revisions/{n}/export`). Every honesty constraint
lives once, in the projection: no internal workflow state in the conformance column, no draft status
presented as a decision, no criterion omitted for being inconvenient.

Every format states on its own face that it is not a VPAT.

**So the gap row 13 names is narrower than it sounds.** It is not "build a Word export" — that
exists, is gated, and is reachable from the UI. It is: the section headings, front matter, ordering
and wording of the official template, and the right to call the result what customers ask for.

### A correction to something this repo has said three times

`api/acr_export_preview.py:8` states, and my own PR bodies repeated, that

> vendoring a third-party artifact (ADR 0029, the PDF analyser) is that it gets its own ADR first.

**ADR 0029 contains no licensing or trademark reasoning at all.** Its only mention of the word
LICENSE is the observation that neither vendored engine *carries* a LICENSE file. It is a
reproducibility and build-integrity decision about a first-party analyser that was already shipping
and could not be rebuilt from source control.

The instinct — write the decision down before copying someone else's artifact into the tree — is
right. ADR 0029 is simply not evidence for it, and citing it as though it settled a licensing
question makes a norm look already-decided when nobody has decided it. This ADR is the first in
this repo to consider a third-party licensing question at all. That is the honest precedent, and it
is a weaker one than the code comments imply.

---

## The question is three questions, and they have different answers

Collapsing them is what makes this look like one large blocked thing rather than three items of
very different size.

### Q1 — Trademark: may a document ACP generates be *called* a VPAT?

The customer-facing half. When a procurement team asks a vendor "send us your VPAT", the word is
what they are asking for. This is the question with legal content, and it is the one that governs
whether the current export is *sufficient but mislabelled* or *actually insufficient*.

### Q2 — Copyright: may the template file be copied into this repo and redistributed?

The vendoring half — the one the code comments have been treating as the whole question. Note it is
strictly narrower than Q1: a permission to *use* the template to produce a document is not
automatically a permission to *redistribute the template itself* inside a commercial product's
source tree, and this repo ships to customers as container images.

### Q3 — Structure: does the shape require the template file at all?

**This one is an engineering question and it is already answered: no.** The projection renders the
four tables, the column meanings and the four conformance terms today, without the file. What the
template adds is exact section text, front matter, ordering, and the name.

That matters for sequencing: Q3 means there is a version of "follows the official structure" that
needs no vendoring — see Option C — and a version that needs Q2 answered yes.

---

## What could not be established from this session, and must not be guessed

**I could not read ITI's published terms — and on 2026-09-07 that stopped being true.** This
section said `www.itic.org` was blocked by the egress proxy. It answered `200` on the next
attempt, a day later, from the same environment. The original caution was right and the conclusion
drawn from it has expired: **the terms below are now quoted from the page, not summarised from
memory.** What the block did NOT mean was that the terms were unknowable; it meant one session
could not reach them, and that is a fact with a shelf life. Re-test a blocked host before building
a decision on its being blocked.

### What the page says, verbatim

Quoted from `https://www.itic.org/policy/accessibility/vpat`, read 2026-09-07. These are ITI's
words, not a paraphrase, because the paraphrase is the failure mode this section was written about:

> The VPAT is offered free of charge. Membership in ITI is not required to use the VPAT. Please
> note, however, that the VPAT name and report form are ITI registered service marks, and should
> not be altered without the express written permission of ITI. Also, the notation ® should be
> used in conjunction with the name and report in accordance with established guidelines.

and, in the list headed *All four editions of the VPAT contain*:

> Provided as a Microsoft Word file that can be used as is or reproduced in other formats.

and, on the naming question:

> A version of the VPAT which has been completed for a specific product is an ACR.

> ITI provides the VPAT templates as a free resource for anyone to use.

**These sentences do not all point the same way, which is why Q1 stays open.** "Reproduced in other
formats" contemplates exactly what ACP does — one projection rendered as HTML, PDF and DOCX. "The
report form … should not be altered" cuts the other way against a structure that resembles the form
without being it. Reading those two together is a legal judgement, and this ADR still does not make
it. What it can now do is put the actual text in front of whoever does.

**What a human still needs to read, for Q1:** whatever trademark/usage notice accompanies the mark
itself. The page quoted above is the terms accompanying the template download; it names the mark
and the alteration constraint, and it does not, on its face, address redistribution inside a
commercial product's source tree and container images. **Silence is not permission**, which is why
the owner's decision below is a decision not to vendor rather than a finding that vendoring is
allowed.

**This is a question for counsel, not for engineering judgement, and not for mine.** What
engineering can say is what each possible answer would cost, which is the rest of this document.

---

## Options, priced against each possible answer

### Option A — Ship what exists; never use the name

**Requires:** nothing. This is today's state.

**Cost:** a customer who asks for "a VPAT" receives an accessible Word document with the right rows
in the right shape, that says on its first page it is not a VPAT. For some procurement processes
that is fine; for others the word is the deliverable. Nobody in this repo can tell you which of
those your customers are — that is a sales input, not a code one.

**Keeps:** every honesty property, and the entire export chain as built.

### Option B — Vendor the template, if and only if Q2 comes back yes

**Requires:** Q2 answered affirmatively **in writing**, for redistribution in a commercial product,
not merely "free to download and use".

**Mechanics, if it happens:** the renderer is what changes; the projection is not. `acr_export_docx`
already consumes `project()` and would fill the template's tables from the same rows, so the swap is
contained to one module and its fixtures. The accessibility gate (row 14) runs over the result
unchanged, which is the property that makes this a safe swap rather than a rewrite — a template that
produced an inaccessible document would be *refused by the gate that already exists*, not shipped.

**Also requires**, and this is the part that is easy to leave out: a vendored third-party artifact
needs a recorded provenance (which edition, downloaded when, from where), a LICENSE or terms file
beside it, and a plan for what happens when ITI publishes a new revision. ADR 0029's precedent is
explicitly *not* helpful here — it vendored engines that carry no LICENSE file, which is exactly
what must not be repeated for a third-party document.

### Option C — Match the published structure without vendoring the file

**Requires:** Q1 and Q2 can both be *no* and this still ships. It is the option available when the
terms turn out to be restrictive.

The section headings and ordering of a published standard document are, in substance, a
specification; implementing to a specification is not the same act as redistributing the document
that states it. **I am flagging this as the option most likely to be over-claimed** — whether it is
actually available depends on Q1/Q2 and is not for me to assert. If counsel says the structure may
be matched but the name may not be used, this is the option that ships.

**Cost:** the output looks like a VPAT and is not called one — Option A's customer problem, with a
closer structural match.

### Option D — Ask ITI

**Requires:** someone to send the question. Slow, and the only route that can turn Q1 from
"unknown" into "yes".

Worth naming because Options A and C are both *permanent workarounds for an unanswered question*,
and the question is answerable by asking it.

---

## What is reversible, and what is not

The asymmetry that should drive the order of operations:

- **Vendoring, then removing:** recoverable. It is a file in a tree and a renderer swap.
- **Shipping a document that calls itself a VPAT without the right to:** not recoverable. It has
  left the building, in the hands of a customer's procurement team, attached to a compliance claim.

So the safe order is: answer Q1 before any output uses the name, and answer Q2 before any file
enters the tree. Nothing about the current export needs to change while those are outstanding —
which is the practical argument for leaving row 13 open rather than treating it as a blocker.

---

## Invariants that survive whichever option is chosen

These are properties of the projection, not of the renderer, and no template may be allowed to
override them:

1. **No internal workflow state in the conformance column.** `_conformance_cell` refuses, and
   `tests/test_acr_export_preview_guard.py` exists because a green suite had already been mistaken
   for evidence that it worked.
2. **No draft status presented as a decision.**
3. **No criterion omitted for being inconvenient** — every applicable criterion appears, including
   the undecided ones.
4. **The generated document passes ACP's own accessibility checks** (row 14, "no FAIL", enforced at
   the route). A conformance report that is itself inaccessible is the one document this product
   cannot hand over, and that must remain true of a templated one.

If a vendored template makes any of these harder to hold, that is an argument against the template,
not against the invariant.

---

## The decision, and what it does not cover

**2026-09-07, the owner: titles and numbers only — the same scope given for EN 301 549 a day
earlier, extended to this template.** In the three-question frame above that is an answer to **Q2**,
and it is a *no* to vendoring with a *yes* to reproducing the template's section headings, table
titles and column headers. It selects **Option C**.

**It is not an answer to Q1**, and Q1 is the irreversible one. A reproduction-scope decision is
about copyright; whether a document may be *called* a VPAT® is about a service mark, and the page
quoted above says that mark should not be altered without ITI's written permission. So:

- every format keeps the statement on its face that it is not a VPAT, exactly as today;
- nothing ACP generates uses the mark, with or without the ® notation;
- the section headings, table titles and column headers may be matched, because those are what
  "titles and numbers" means for a document whose content is a table structure.

**What this permits ACP to reproduce**, and the boundary is the same one the EN 301 549 catalog
runs on: *headings and table structure, not prose*. The template's Essential Requirements, Best
Practices, Terms and Legal Disclaimer sections are instructional and boilerplate text — they are
the prose, and they stay out. A heading with ACP's own words under it is not a reproduction of
ITI's; a heading with ITI's paragraph under it would be.

### A finding from reading the template itself

The WCAG edition lists **56** criteria where `config/wcag-2.2-aa.json` holds **55**. The whole
difference is **4.1.1 Parsing**, which the template carries annotated *"WCAG 2.0 and 2.1 – Always
answer 'Supports'; WCAG 2.2 (obsolete and removed) - Does not apply"* so that one template serves
all three WCAG versions. ACP's catalog is WCAG 2.2 and correctly omits it. **This is not a gap to
close** — adding 4.1.1 to a 2.2 report would print a criterion the standard removed. Recorded
because "the official template has one more row than we do" is exactly the observation that gets
acted on before it is understood.

Every one of the other 55 titles matches ACP's, case-folded, once the template's `(Level A)` /
`(Level AA 2.1 and 2.2)` suffix is stripped — the level is a rendering convention there, and a
column in ACP's catalog.

## Prior decision (superseded for Q2 on 2026-09-07)

**Deferred, pending Q1 and Q2.** Recorded here rather than left implicit so that:

- row 13 stops reading as an engineering backlog item, which it is not;
- the three questions stop being one question, since Q3 is already answered and Q1 is the only one
  with legal content;
- the ADR-0029-as-licensing-precedent claim stops propagating, since it is not one.

**Recommended sequence** (engineering's input to a decision that is not engineering's to make):
send Q1 and Q2 to counsel or to ITI (Option D) while shipping Option A, which is already live. Do
not begin Option B before Q2 is answered in writing.

*Followed, in part.* Q2 was answered by the owner on 2026-09-07 as a scope rather than a
permission — reproduce titles and numbers, do not vendor the file — which selects Option C and
leaves Option B unbegun, as this sequence asks. Q1 has not been sent, and until it is, Option A's
disclaimer stays on every rendered format. Option C changes the shape of the document; it does not
change what the document is allowed to call itself.

## Consequences

- `docs/prd-acr-workspace.md` row 13 should reference this ADR rather than the phrase "blocked on
  the licensing decision", which does not say who decides or what they must read.
- The `ADR 0029` citations in `api/acr_export_preview.py` and `api/acr_export_docx.py` should point
  here instead. They are not wrong about wanting an ADR; they are wrong about which one, and about
  there having been one.
- If Q2 is answered yes, Option B's provenance requirements (edition, date, source, terms file,
  revision plan) are part of that work and not a follow-up.
