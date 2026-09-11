export default function ReviewDetails({ children }) {
  return <details className="remediation-secondary-details">
    <summary>Audit trail, due date and comments</summary>
    <div style={{ marginTop: 12 }}>{children}</div>
  </details>
}
