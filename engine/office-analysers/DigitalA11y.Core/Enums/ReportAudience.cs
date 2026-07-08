namespace DigitalA11y.Core.Enums;

public enum ReportAudience
{
    Developer,   // technical detail: element paths, rule IDs, raw analyser output refs
    Client,      // plain language, business impact framing, no unexpanded acronyms
    Compliance,  // formal, standards-referenced, WCAG criterion + HiTrust CSF control citations
    All          // all audience tiers; content diverges per section with sub-section labels
}
