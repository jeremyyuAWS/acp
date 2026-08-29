// Plain-language definitions for KPI labels and terms that read as jargon out of context.
//
// Each entry is deliberately short (one or two sentences) — a hover definition that itself
// needs explaining has failed at the one thing it's for. Wording mirrors language already
// established elsewhere in the product (unreadableWhy.js, classificationData.js, the Discover
// results copy) rather than inventing a second phrasing of the same fact.
//
// Add a term here, then wrap its label with <Term k="that-key">label text</Term> (see Term.jsx) —
// nothing else needs to change at the call site.
export const GLOSSARY = {
  unreadable: {
    term: 'Could not be read',
    body: 'ACP tried to read this file’s metadata and could not — usually because it’s '
      + 'password-protected, in a format ACP doesn’t support, or the source returned an error '
      + 'when asked for it. It is still counted in the estate; nothing about it was skipped or ignored.',
  },
  not_measured: {
    term: 'Not measured',
    body: 'No source provides this value yet, so nothing was computed. Shown as absent rather '
      + 'than as a zero — a zero would claim a real measurement came back empty, which isn’t '
      + 'what happened here.',
  },
  unclassified_estate: {
    term: 'Unclassified',
    body: 'Discovery reads a file’s name, path, size and date. It does not yet derive a '
      + 'department or a sensitivity label from the document itself, and no connected source '
      + 'supplies one — so there is nothing real to group or tag by here.',
  },
  lifecycle_recommendation: {
    term: 'Lifecycle recommendation',
    body: 'A tag an enabled rule attached during discovery (e.g. “last modified before …”). '
      + 'It is only ever a suggestion — nothing is archived, moved or deleted. You confirm or '
      + 'override each one before it does anything.',
  },
  auto_fixable: {
    term: 'Auto-fix available',
    body: 'Findings with a deterministic remediation action — the same input always produces the '
      + 'same fix, with no judgement call involved. Excludes AI-drafted suggestions, which are '
      + 'counted under human review instead.',
  },
  unsupported_format: {
    term: 'Unsupported',
    body: 'A file format ACP does not parse for accessibility at all. It is listed in the '
      + 'inventory, but there is no assessment lane for this format yet — independent of what the '
      + 'file itself contains.',
  },
  metadata_only_format: {
    term: 'Metadata-only',
    body: 'An image, audio, or video file. Discovery lists it from its metadata, but ACP has no '
      + 'accessibility test for this format — the file is inventoried, never opened.',
  },
  eligibility_unknown: {
    term: 'Eligibility unknown',
    body: 'ACP has not yet classified this file into an assessable or unsupported bucket. It is '
      + 'counted in the inventory, but which lane it belongs to is not yet determined.',
  },
  excluded_from_scope: {
    term: 'Excluded',
    body: 'ACP’s own output, or a file excluded by policy — not part of the content you asked ACP '
      + 'to assess.',
  },
  // Same underlying fact as `unreadable` above (a file the engine tried to open and could not) —
  // a separate entry only because the two call sites use different visible wording ("could not
  // be read" vs "could not be opened") and the tooltip's own heading should say what the label
  // beside it says, not a different phrase for the same thing.
  could_not_be_opened: {
    term: 'Could not be opened',
    body: 'ACP tried to read this file’s metadata and could not — usually because it’s '
      + 'password-protected, in a format ACP doesn’t support, or the source returned an error '
      + 'when asked for it. It is still counted in the estate; nothing about it was skipped or ignored.',
  },
}
