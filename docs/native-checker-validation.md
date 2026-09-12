# Independent native checker validation

Validation on September 12, 2026 used isolated synthetic documents, the supported production writers and real independent checkers. It establishes specific working repairs, not customer-batch completeness or universal accessibility.

## Microsoft Word Accessibility Assistant

Actual Word for Mac version 16.111.3 opened the synthetic DOCX controls through the native UI. Review > Check Accessibility displayed:

| Control | Missing alt text | Other displayed issues | Native result |
| --- | ---: | ---: | --- |
| No drawing title or description | 1 | 0 | Accessibility Investigate |
| Supported approved-alt writer corrected copy | 0 | 0 | Looks good No issues found |
| Descriptive drawing title only | 0 | 0 | Looks good No issues found |

The corrected copy retained the original body, headings, table and image. The image's existing drawing property gained the explicit description through `apply_alt_text`. Word accepts a descriptive title alone, while ACP deliberately checks for a description: the title-only result is a native control, not proof the ACP description writer was unnecessary.

Displayed categories checked were hard-to-read contrast, missing alt text, missing table header, merged/split cells, no headings and restricted access. Results do not cover every possible Office object or the user's published SharePoint copies. The exact source/corrected DOCX controls are retained beside the evidence. The observed file hashes and application version are saved in `docs/evidence/native-checkers-2026-09-12/word-assistant-observation.json`. No customer recent document was opened or altered.

## veraPDF PDF UA 1

The actual installed veraPDF 1.30.2 PDF/UA-1 profile produced:

| Control | Failed rules | Failed checks | Profile result |
| --- | ---: | ---: | --- |
| WeasyPrint PDF/UA-1 tagged positive control | 0 | 0 | Pass |
| Same content untagged negative control | 5 | 6 | Fail |
| Existing tagged preservation fixture before repairs | 11 | 21 | Fail |
| Same fixture after exact heading and header-scope repairs | 10 | 20 | Fail |

The positive control passed 106 rules and 274 checks. The repair fixture cleared the native table header scope failure under clause 7.5. Its remaining deliberately unaddressed fixture failures include nonembedded font programs, language/metadata/catalog settings and untagged/unlabelled annotation/link semantics. A tag repair is not permission to declare the complete document PDF/UA compliant. Canonical fresh assessment remains separate from this stricter independent corroboration.

The exact four PDF controls and their SHA256 manifest are retained beside the evidence. The complete native machine report is retained in `docs/evidence/native-checkers-2026-09-12/verapdf-ua1-results.json`. veraPDF exited 1 because negative controls fail by design; the reports were inspected, not treated as a successful universal validator pass. Acrobat is not installed, so Acrobat Accessibility Checker has not been run.

## Reproduce

Build controls with the project test environment:

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/build_native_checker_controls.py /tmp/acp-native-controls
```

Open only the generated `word-missing-alt.docx` and `word-approved-alt-corrected.docx` in Word and run Review > Check Accessibility. If Word disables files under `/tmp`, use a dedicated generated folder under Downloads. Do not replace an actual native checker run with the fixture's file manifest.

```sh
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
  /Users/css173265/.codex/dependencies/acp-verapdf/verapdf \
  --flavour ua1 --format json /tmp/acp-native-controls/*.pdf
```

The generated positive and negative controls verify the checker is actually functioning. Inspect each result and clause; expected failing controls mean a nonzero aggregate exit is normal.
