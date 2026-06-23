import { useState, useRef } from 'react'
import Rubric from './Rubric.jsx'
import WcagCoverage from './WcagCoverage.jsx'
import Ontology from './Ontology.jsx'
import OwnerDelegate from './OwnerDelegate.jsx'
import FileTypeConfig from './FileTypeConfig.jsx'
import RolePrivilege from './RolePrivilege.jsx'
import UserManagement from './UserManagement.jsx'
import { useDialog } from './a11y.js'
import { downloadUpdatedXlsx, downloadUpdatedPptx } from './exportDeliverables.js'

// Platform settings, behind the header cog — gated to the Platform Admin. Holds
// the scoring rules (Rubric), the validation coverage (WCAG 2.1 + 2.2 matrix), and
// the business ontology/taxonomy — i.e. the configuration an admin owns, kept out
// of the day-to-day workflow tabs.
export default function Settings({ onClose, onRubricSaved, files = [], onOntologyChange, onDelegationChange, onFileTypeChange, onPrivilegeChange }) {
  const [tab, setTab] = useState('rules')
  const [dl, setDl] = useState(null) // 'xlsx' | 'pptx' while a deliverable is generating
  const panelRef = useRef(null)
  useDialog(panelRef, onClose)
  const grab = async (kind, fn) => { if (dl) return; setDl(kind); try { await fn() } catch (e) { console.error('deliverable export failed', e) } finally { setDl(null) } }
  return (
    <div className="setoverlay" role="dialog" aria-modal="true" aria-label="Platform settings" onClick={onClose}>
      <div className="setpanel" ref={panelRef} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <div className="sethead">
          <div><b>⚙ Platform settings</b><span className="muted"> · admin · rules &amp; validation</span></div>
          <button className="ghost small" aria-label="Close settings" onClick={onClose}>✕</button>
        </div>
        <div className="setexports">
          <span className="setexporthint">Updated deliverables — original format, with a live <b>Status</b> column reflecting what the platform ships today:</span>
          <div className="setexportbtns">
            <button className="dlbtn" disabled={!!dl} onClick={() => grab('xlsx', downloadUpdatedXlsx)}>{dl === 'xlsx' ? 'Preparing…' : '⤓ Coverage matrix · Excel'}</button>
            <button className="dlbtn" disabled={!!dl} onClick={() => grab('pptx', downloadUpdatedPptx)}>{dl === 'pptx' ? 'Preparing…' : '⤓ Method deck · PPT'}</button>
          </div>
        </div>
        <div className="subtabs" role="tablist" aria-label="Settings sections">
          <button role="tab" aria-selected={tab === 'rules'} className={tab === 'rules' ? 'fchip on' : 'fchip'} onClick={() => setTab('rules')}>Scoring rules</button>
          <button role="tab" aria-selected={tab === 'validation'} className={tab === 'validation' ? 'fchip on' : 'fchip'} onClick={() => setTab('validation')}>Validation coverage</button>
          <button role="tab" aria-selected={tab === 'ontology'} className={tab === 'ontology' ? 'fchip on' : 'fchip'} onClick={() => setTab('ontology')}>Business ontology</button>
          <button role="tab" aria-selected={tab === 'filetypes'} className={tab === 'filetypes' ? 'fchip on' : 'fchip'} onClick={() => setTab('filetypes')}>File types</button>
          <button role="tab" aria-selected={tab === 'owners'} className={tab === 'owners' ? 'fchip on' : 'fchip'} onClick={() => setTab('owners')}>Owners</button>
          <button role="tab" aria-selected={tab === 'permissions'} className={tab === 'permissions' ? 'fchip on' : 'fchip'} onClick={() => setTab('permissions')}>Permissions</button>
          <button role="tab" aria-selected={tab === 'users'} className={tab === 'users' ? 'fchip on' : 'fchip'} onClick={() => setTab('users')}>Users</button>
        </div>
        <div className="setbody">
          {tab === 'rules' && <Rubric onSaved={onRubricSaved} />}
          {tab === 'validation' && <WcagCoverage />}
          {tab === 'ontology' && <Ontology files={files} onPublished={onOntologyChange} />}
          {tab === 'filetypes' && <FileTypeConfig onChanged={(cfg, custom) => onFileTypeChange?.(cfg, custom)} />}
          {tab === 'owners' && <OwnerDelegate files={files} onChanged={onDelegationChange} />}
          {tab === 'permissions' && <RolePrivilege onChanged={onPrivilegeChange} />}
          {tab === 'users' && <UserManagement />}
        </div>
      </div>
    </div>
  )
}
