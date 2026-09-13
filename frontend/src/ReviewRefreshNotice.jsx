export default function ReviewRefreshNotice({ error, onRetry }) {
  if (!error) return null
  const denied = [401,403].includes(error.status)
  const missing = error.status === 404
  return <div role="alert" className="rem-act-error" style={{margin:'0 0 12px',padding:'10px 12px',borderRadius:8,fontSize:13,background:'#FFF8E6',color:'#805300',border:'1px solid #E9D4A8'}}>
    <strong>Review status could not be updated.</strong>{' '}
    {denied ? 'Your session cannot read this run. Sign in again to refresh its status.'
      : missing ? 'This run could not be found. Reopen the current scan to check its review status.'
        : 'The latest review status could not be loaded. The displayed counts are the last recorded values; this message does not mean saved fixes failed.'}
    {!denied && !missing && onRetry && <button className="linkbtn" onClick={onRetry} style={{marginLeft:8}}>Retry status update</button>}
  </div>
}
