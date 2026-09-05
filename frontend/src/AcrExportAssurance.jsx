// Keep the in-product assurance statement aligned with api/acr_export_pdf.py::UNRUN_GATES.
// The server remains the authority for the exported artifact; this card makes the same limits
// visible before someone downloads and circulates it.
export default function AcrExportAssurance() {
  return (
    <section className="acr-assurance" aria-labelledby="acr-assurance-heading">
      <div className="acr-assurance__intro">
        <p className="eyebrow">Export assurance</p>
        <h3 id="acr-assurance-heading">Machine-checked, with validation still outstanding</h3>
        <p>
          ACP checks the exported report as PDF/UA-1 with veraPDF and asserts its structure tree
          in automated tests. Those checks are necessary, but they do not prove that a person
          using a screen reader can successfully read the document.
        </p>
      </div>
      <ul className="acr-assurance__checks" aria-label="ACR PDF validation gates">
        <li>
          <span className="acr-assurance__mark acr-assurance__mark--done" aria-hidden="true">✓</span>
          <span><strong>Automated PDF checks</strong><small>PDF/UA-1 and structure-tree checks</small></span>
          <b className="acr-assurance__state acr-assurance__state--done">Checked</b>
        </li>
        <li>
          <span className="acr-assurance__mark" aria-hidden="true">○</span>
          <span><strong>PAC 2024</strong><small>Independent PDF accessibility validation</small></span>
          <b className="acr-assurance__state">Not run</b>
        </li>
        <li>
          <span className="acr-assurance__mark" aria-hidden="true">○</span>
          <span><strong>Screen-reader review</strong><small>NVDA or VoiceOver reading pass</small></span>
          <b className="acr-assurance__state">Not run</b>
        </li>
      </ul>
      <p className="acr-assurance__limit">
        <strong>Current claim:</strong> machine-validated draft—not a completed accessibility
        validation or evidence of successful screen-reader use.
      </p>
    </section>
  )
}
