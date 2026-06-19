import { useState, useMemo, useEffect } from 'react'
import { LS_KEY, FIELDS, deriveOptions, evalRule, riskFactors, riskScore, parseNL, PRI_COLOR, PRIORITY_W, condText, worstSev, exposureOf, taxonomyPaths, DEFAULT_LABELS, DEFAULT_RULES, DEFAULT_TAXONOMY, DEFAULT_PUBLISHED } from './ontology.js'

// Custom Ontology & Business Taxonomy Manager (Admin). An admin teaches the platform
// their org's own document model — custom labels, a hierarchical taxonomy, and a
// metadata rules engine that PRIORITISES/CATEGORISES the real corpus. The shared engine
// lives in ./ontology.js, so the live workflow (Remediate queue, Overview, file drawer)
// classifies from the same source of truth. NL authoring is a real deterministic parser;
// AI example-learning, relationships and rollback are clearly-labelled previews.

const DEFAULT_STATE = {
  labels: DEFAULT_LABELS.map((l) => ({ ...l })),
  taxonomy: JSON.parse(JSON.stringify(DEFAULT_TAXONOMY)),
  rules: DEFAULT_RULES.map((r) => ({ ...r })),
  version: 1, status: 'published', publishedAt: 'seeded', published: DEFAULT_PUBLISHED,
  history: [{ v: 1, at: 'seeded', by: 'system', rules: DEFAULT_RULES.length, labels: DEFAULT_LABELS.length, snap: { rules: DEFAULT_RULES, labels: DEFAULT_LABELS } }],
}
const load = () => {
  try {
    const s = JSON.parse(localStorage.getItem(LS_KEY))
    if (s && s.labels) { if (!s.published) s.published = { version: s.version || 1, at: s.publishedAt || 'seeded', by: 'admin', rules: s.rules, labels: s.labels }; return s }
    return DEFAULT_STATE
  } catch { return DEFAULT_STATE }
}
let _id = 100
const nid = (p) => `${p}${_id++}`

function Tree({ node, depth = 0, path = '', onAdd, onRemove, count }) {
  const full = path ? `${path} / ${node.name}` : node.name
  const c = count ? count(full) : 0
  return (
    <div className="onttreenode" style={{ marginLeft: depth ? 16 : 0 }}>
      <div className="onttreerow">
        <span className="onttreename">{depth > 0 && <span className="onttreeglyph" aria-hidden="true">{'└ '}</span>}{node.name}{c > 0 && <span className="ontcount muted">{c.toLocaleString()}</span>}</span>
        <span className="onttreeacts">
          <button className="ghost small" onClick={() => onAdd(node)} title="Add a child category">＋</button>
          {depth > 0 && <button className="ghost small" onClick={() => onRemove(node)} title="Remove">✕</button>}
        </span>
      </div>
      {(node.children || []).map((ch, i) => <Tree key={i} node={ch} depth={depth + 1} path={full} onAdd={onAdd} onRemove={onRemove} count={count} />)}
    </div>
  )
}

export default function Ontology({ files = [], onPublished }) {
  const [st, setSt] = useState(load)
  const [tab, setTab] = useState('taxonomy')
  const [nl, setNl] = useState('')
  const [nlRule, setNlRule] = useState(null)
  const [draft, setDraft] = useState(() => ({ name: '', match: 'all', conditions: [{ field: 'department', op: 'is', value: '' }], actions: { priority: 'High', slaDays: null, label: '', category: '' } }))
  const [editId, setEditId] = useState(null)
  const blankDraft = () => ({ name: '', match: 'all', conditions: [{ field: 'department', op: 'is', value: '' }], actions: { priority: 'High', slaDays: null, label: '', category: '' } })
  const opts = useMemo(() => deriveOptions(files), [files])
  useEffect(() => { try { localStorage.setItem(LS_KEY, JSON.stringify(st)) } catch { /* ignore */ } }, [st])
  const dirty = st.status === 'draft' || st.dirty
  const set = (patch) => setSt((s) => ({ ...s, ...patch, status: 'draft', dirty: true }))

  // ---- evaluation against the real corpus ----
  const matchesFor = (rule) => files.filter((f) => evalRule(f, rule))
  // first matching rule wins for a doc's classification
  const classified = useMemo(() => files.map((f) => {
    const rule = st.rules.find((r) => evalRule(f, r))
    return { f, rule, priority: rule?.actions?.priority || null, label: rule?.actions?.label || null, category: rule?.actions?.category || null, score: rule ? riskScore(f, rule.actions?.priority) : 0 }
  }), [files, st.rules])
  const covered = classified.filter((c) => c.rule)
  const ranked = [...covered].sort((a, b) => b.score - a.score).slice(0, 12)
  const labelName = (id) => st.labels.find((l) => l.id === id)?.name
  const taxPaths = useMemo(() => taxonomyPaths(st.taxonomy), [st.taxonomy])
  const labelCount = (id) => covered.filter((c) => c.label === id).length
  const catCount = (path) => covered.filter((c) => c.category === path).length
  // Overlap: first matching rule wins, so a later rule's docs already claimed by an earlier
  // rule are "shadowed" — its conditions never decide those documents.
  const ruleSets = useMemo(() => st.rules.map((r) => new Set(files.filter((f) => evalRule(f, r)).map((f) => f.file))), [st.rules, files])
  const shadowOf = (i) => { const mine = ruleSets[i] || new Set(); let s = 0; mine.forEach((file) => { for (let j = 0; j < i; j++) if (ruleSets[j].has(file)) { s++; break } }); return { total: mine.size, shadowed: s } }
  // Publish gate — every rule needs at least one fully-specified condition.
  const invalidRules = st.rules.filter((r) => !(r.conditions || []).length || r.conditions.some((c) => c.value === '' || c.value == null))
  const canPublish = dirty && invalidRules.length === 0

  // ---- handlers ----
  const addLabel = () => set({ labels: [...st.labels, { id: nid('l'), name: 'New label', color: '#1F5FA8' }] })
  const editLabel = (id, patch) => set({ labels: st.labels.map((l) => l.id === id ? { ...l, ...patch } : l) })
  const delLabel = (id) => set({ labels: st.labels.filter((l) => l.id !== id) })
  const addCat = (parent) => { const name = prompt('Category name'); if (!name) return; parent.children = [...(parent.children || []), { name }]; set({ taxonomy: { ...st.taxonomy } }) }
  const rmCat = (node) => { const strip = (n) => ({ ...n, children: (n.children || []).filter((c) => c !== node).map(strip) }); set({ taxonomy: strip(st.taxonomy) }) }
  const addRule = (r) => set({ rules: [...st.rules, { ...r, id: nid('r') }] })
  const delRule = (id) => set({ rules: st.rules.filter((r) => r.id !== id) })
  const addCond = () => setDraft((d) => ({ ...d, conditions: [...d.conditions, { field: 'department', op: 'is', value: '' }] }))
  const setCond = (i, patch) => setDraft((d) => ({ ...d, conditions: d.conditions.map((c, n) => n === i ? { ...c, ...patch } : c) }))
  const rmCond = (i) => setDraft((d) => ({ ...d, conditions: d.conditions.filter((_, n) => n !== i) }))
  const startEdit = (r) => { setDraft({ name: r.name, match: r.match, conditions: r.conditions.map((c) => ({ ...c })), actions: { priority: 'High', slaDays: null, label: '', ...r.actions } }); setEditId(r.id) }
  const commitDraft = () => {
    if (!draft.conditions.length) return
    const name = draft.name || draft.conditions.map(condText).join(draft.match === 'any' ? ' OR ' : ' AND ').slice(0, 60)
    if (editId) { set({ rules: st.rules.map((r) => r.id === editId ? { ...draft, name, id: editId } : r) }); setEditId(null) }
    else addRule({ ...draft, name })
    setDraft(blankDraft())
  }
  const publish = () => {
    const now = new Date().toLocaleString()
    const v = st.version + (st.status === 'draft' ? 1 : 0)
    const next = { ...st, status: 'published', dirty: false, version: v, publishedAt: now,
      published: { version: v, at: now, by: 'admin', rules: st.rules, labels: st.labels },
      history: [{ v, at: now, by: 'admin', rules: st.rules.length, labels: st.labels.length, snap: { rules: st.rules, labels: st.labels } }, ...(st.history || [])].slice(0, 12) }
    try { localStorage.setItem(LS_KEY, JSON.stringify(next)) } catch { /* ignore */ }
    setSt(next)
    onPublished?.()
  }
  // Restore a published version's rules + labels as an editable draft (review, then re-publish).
  const rollback = (h) => { if (!h.snap) return; setEditId(null); setDraft(blankDraft()); setSt((s) => ({ ...s, rules: h.snap.rules.map((r) => ({ ...r })), labels: h.snap.labels.map((l) => ({ ...l })), status: 'draft', dirty: true })); setTab('rules') }

  const condCtl = (c, i) => {
    const fd = FIELDS[c.field]
    return (
      <div className="ontcond" key={i}>
        <select aria-label="Condition field" value={c.field} onChange={(e) => setCond(i, { field: e.target.value, op: FIELDS[e.target.value].ops[0], value: '' })}>
          {Object.entries(FIELDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select aria-label="Condition operator" value={c.op} onChange={(e) => setCond(i, { op: e.target.value })}>{fd.ops.map((o) => <option key={o}>{o}</option>)}</select>
        {fd.type === 'enum' || fd.type === 'sev'
          ? <select aria-label="Condition value" value={c.value} onChange={(e) => setCond(i, { value: e.target.value })}><option value="">choose…</option>{(opts[c.field] || []).map((o) => <option key={o}>{o}</option>)}</select>
          : <input aria-label="Condition value" value={c.value} placeholder={fd.unit || 'value'} onChange={(e) => setCond(i, { value: e.target.value })} />}
        {draft.conditions.length > 1 && <button className="ghost small" onClick={() => rmCond(i)} aria-label="Remove condition">✕</button>}
      </div>
    )
  }

  const RuleCard = ({ r, idx }) => {
    const n = matchesFor(r).length
    const [fg, bg] = PRI_COLOR[r.actions?.priority] || PRI_COLOR.Medium
    const sh = shadowOf(idx)
    return (
      <div className="ontrule">
        <div className="ontruletop">
          <b>{r.name}</b>
          <span className="ontpri" style={{ color: fg, background: bg }}>{r.actions?.priority}{r.actions?.slaDays ? ` · ${r.actions.slaDays}d SLA` : ''}</span>
          <button className="ghost small" onClick={() => startEdit(r)} aria-label="Edit rule" style={{ marginLeft: 'auto' }}>✎ Edit</button>
          <button className="ghost small" onClick={() => delRule(r.id)} aria-label="Delete rule">✕</button>
        </div>
        <div className="ontrulecond">{(r.conditions || []).map((c, i) => <span key={i} className="ontchip">{condText(c)}{i < r.conditions.length - 1 && <em className="ontjoin"> {r.match === 'any' ? 'OR' : 'AND'} </em>}</span>)}</div>
        <div className="ontrulefoot"><span className="ontmatch">⟶ matches <b>{n.toLocaleString()}</b> of {files.length.toLocaleString()} documents</span>{r.actions?.label && labelName(r.actions.label) && <span className="muted"> · labels “{labelName(r.actions.label)}”</span>}{r.actions?.category && <span className="muted"> · files under {r.actions.category}</span>}{sh.shadowed > 0 && <span className="ontwarn">⚠ {sh.shadowed === sh.total ? 'fully shadowed by an earlier rule — never applies' : `${sh.shadowed} of ${sh.total} also matched earlier (first rule wins)`}</span>}</div>
      </div>
    )
  }

  return (
    <div className="ontwrap">
      <div className="ontbar">
        <div>
          <b>Business ontology &amp; taxonomy</b>
          <div className="muted" style={{ marginTop: 2 }}>Teach the platform your org's document model — labels, taxonomy &amp; prioritisation rules that classify the real estate. {files.length.toLocaleString()} documents in scope.</div>
        </div>
        <div className="ontpublish">
          <span className={dirty ? 'ontstatus draft' : 'ontstatus live'}>{dirty ? '● Draft — unpublished changes' : `✓ Published v${st.version} · live in the queue`}</span>
          <button onClick={publish} disabled={!canPublish} title={invalidRules.length ? `${invalidRules.length} rule(s) have an unset condition value` : ''}>Publish ontology</button>
        </div>
      </div>

      {invalidRules.length > 0 && <div className="ontvalwarn">⚠ {invalidRules.length} rule{invalidRules.length === 1 ? '' : 's'} can't be published — a condition has no value{invalidRules[0]?.name ? ` (e.g. “${invalidRules[0].name}”)` : ''}. Fix it on the Rules tab.</div>}

      <div className="subtabs" role="tablist" aria-label="Ontology sections">
        {[['taxonomy', 'Labels & taxonomy'], ['rules', `Rules · ${st.rules.length}`], ['impact', 'Impact & risk'], ['versions', 'Versions & advanced']].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'fchip on' : 'fchip'} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === 'taxonomy' && (
        <div className="ontcols">
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Custom labels</h3><button className="ghost small" onClick={addLabel}>＋ Add label</button></div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Org-specific document types — applied by rules or by hand.</div>
            <div className="ontlabels">
              {st.labels.map((l) => (
                <div className="ontlabel" key={l.id}>
                  <input type="color" value={l.color} onChange={(e) => editLabel(l.id, { color: e.target.value })} aria-label="Label colour" />
                  <input aria-label="Label name" className="ontlabelname" value={l.name} onChange={(e) => editLabel(l.id, { name: e.target.value })} />
                  <span className="ontlabelpill" style={{ color: l.color, background: l.color + '22' }}>{l.name}</span>
                  <span className="ontcount muted">{labelCount(l.id).toLocaleString()} doc{labelCount(l.id) === 1 ? '' : 's'}</span>
                  <button className="ghost small" onClick={() => delLabel(l.id)} aria-label="Delete label">✕</button>
                </div>
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Hierarchical taxonomy</h3></div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Parent/child categories documents can be filed under. Use ＋ to nest.</div>
            <div className="onttree"><Tree node={st.taxonomy} onAdd={addCat} onRemove={rmCat} count={catCount} /></div>
          </section>
        </div>
      )}

      {tab === 'rules' && (
        <>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Natural-language rule</h3><span className="muted" style={{ fontSize: 12 }}>type a rule — we convert it to a deterministic, previewable rule</span></div>
            <div className="ontnl">
              <input aria-label="Natural-language rule" value={nl} placeholder="e.g. Prioritize all externally published policy documents owned by HR and Legal" onChange={(e) => setNl(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') setNlRule(parseNL(nl, opts)) }} />
              <button onClick={() => setNlRule(parseNL(nl, opts))} disabled={!nl.trim()}>Interpret</button>
            </div>
            {nlRule && (
              <div className="ontnlout">
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Interpreted as — review before adding:</div>
                <div className="ontrulecond">{nlRule.conditions.length ? nlRule.conditions.map((c, i) => <span key={i} className="ontchip">{condText(c)}{i < nlRule.conditions.length - 1 && <em className="ontjoin"> {nlRule.match === 'any' ? 'OR' : 'AND'} </em>}</span>) : <span className="muted">no conditions recognised — rephrase or build below</span>}</div>
                {(() => { const ms = files.filter((f) => evalRule(f, nlRule)); return ms.length ? <div className="ontsample"><span className="muted">affected:</span>{ms.slice(0, 5).map((f) => <span key={f.file} className="ontchip">{f.file}</span>)}{ms.length > 5 && <span className="muted">+{(ms.length - 5).toLocaleString()} more</span>}</div> : null })()}
                <div className="ontnlfoot"><span className="ontpri" style={{ color: PRI_COLOR[nlRule.actions.priority][0], background: PRI_COLOR[nlRule.actions.priority][1] }}>{nlRule.actions.priority}{nlRule.actions.slaDays ? ` · ${nlRule.actions.slaDays}d` : ''}</span><span className="muted"> · matches {files.filter((f) => evalRule(f, nlRule)).length.toLocaleString()} docs</span><button className="ghost small" disabled={!nlRule.conditions.length} onClick={() => { addRule({ ...nlRule, name: nl.slice(0, 60) }); setNl(''); setNlRule(null) }} style={{ marginLeft: 'auto' }}>＋ Add this rule</button></div>
              </div>
            )}
          </section>

          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>{editId ? 'Edit rule' : 'Rule builder'}</h3>{editId && <span className="ontprevtag" style={{ background: '#E2EDFB', color: '#1F5FA8' }}>editing</span>}<span className="muted" style={{ fontSize: 12 }}>match
              <select aria-label="Match all or any conditions" value={draft.match} onChange={(e) => setDraft((d) => ({ ...d, match: e.target.value }))} style={{ margin: '0 4px' }}><option value="all">ALL</option><option value="any">ANY</option></select>
              of:</span></div>
            {editId && <input aria-label="Rule name" className="ontlabelname" style={{ width: '100%', marginBottom: 8 }} value={draft.name} placeholder="Rule name" onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />}
            {draft.conditions.map((c, i) => condCtl(c, i))}
            <button className="ghost small" onClick={addCond} style={{ marginTop: 4 }}>＋ Add condition</button>
            <div className="ontaction">
              <span className="muted">then set priority</span>
              <select aria-label="Priority" value={draft.actions.priority} onChange={(e) => setDraft((d) => ({ ...d, actions: { ...d.actions, priority: e.target.value } }))}>{Object.keys(PRIORITY_W).map((p) => <option key={p}>{p}</option>)}</select>
              <span className="muted">label</span>
              <select aria-label="Assign label" value={draft.actions.label} onChange={(e) => setDraft((d) => ({ ...d, actions: { ...d.actions, label: e.target.value } }))}><option value="">none</option>{st.labels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
              <span className="muted">file under</span>
              <select aria-label="Assign category" value={draft.actions.category || ''} onChange={(e) => setDraft((d) => ({ ...d, actions: { ...d.actions, category: e.target.value } }))}><option value="">none</option>{taxPaths.map((p) => <option key={p} value={p}>{p}</option>)}</select>
              <span className="muted">SLA</span>
              <input aria-label="SLA days" style={{ width: 56 }} placeholder="days" value={draft.actions.slaDays || ''} onChange={(e) => setDraft((d) => ({ ...d, actions: { ...d.actions, slaDays: e.target.value ? +e.target.value : null } }))} />
              <span className="ontmatch" style={{ marginLeft: 'auto' }}>preview: <b>{files.filter((f) => evalRule(f, draft)).length.toLocaleString()}</b> match</span>
              <button onClick={commitDraft}>{editId ? 'Save changes' : 'Add rule'}</button>
              {editId && <button className="ghost small" onClick={() => { setEditId(null); setDraft(blankDraft()) }}>Cancel</button>}
            </div>
            {(() => { const ms = files.filter((f) => evalRule(f, draft)); return ms.length && draft.conditions.some((c) => c.value !== '') ? <div className="ontsample"><span className="muted">affected documents:</span>{ms.slice(0, 5).map((f) => <span key={f.file} className="ontchip">{f.file}</span>)}{ms.length > 5 && <span className="muted">+{(ms.length - 5).toLocaleString()} more</span>}</div> : null })()}
          </section>

          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Active rules</h3><span className="muted" style={{ fontSize: 12 }}>first matching rule classifies a document</span></div>
            {st.rules.length ? st.rules.map((r, i) => <RuleCard key={r.id} r={r} idx={i} />) : <p className="muted">No rules yet.</p>}
          </section>
        </>
      )}

      {tab === 'impact' && (
        <>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Weighted risk score</h3></div>
            <div className="ontformula"><code>Overall priority = WCAG severity × business criticality × external exposure × regulatory risk × document usage</code></div>
            <div className="ontstats">
              <div className="ontstat"><b>{covered.length.toLocaleString()}</b><span className="muted">of {files.length.toLocaleString()} classified by your rules</span></div>
              {['Critical', 'High', 'Medium', 'Low'].map((p) => { const n = covered.filter((c) => c.priority === p).length; return <div className="ontstat" key={p}><b style={{ color: PRI_COLOR[p][0] }}>{n}</b><span className="muted">{p} priority</span></div> })}
            </div>
          </section>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Estimated impact — top documents by business risk</h3><span className="muted" style={{ fontSize: 12 }}>how the published ontology re-ranks the remediation queue</span></div>
            <div className="ontranklist">
              {ranked.length ? ranked.map((c, i) => { const fac = riskFactors(c.f, c.priority); const [fg, bg] = PRI_COLOR[c.priority] || PRI_COLOR.Medium; return (
                <div className="ontrankrow" key={i}>
                  <span className="ontrankn">{i + 1}</span>
                  <div className="ontrankmain"><div className="ontrankfile">{c.f.file}</div><div className="muted" style={{ fontSize: 11 }}>{c.f.department} · {exposureOf(c.f)} · {worstSev(c.f).toLowerCase()} finding · {c.f.views90d} views</div></div>
                  <span className="ontpri" style={{ color: fg, background: bg }}>{c.priority}</span>
                  <span className="ontscore" title={`severity ${fac.severity} × criticality ${fac.criticality} × exposure ${fac.exposure} × regulatory ${fac.regulatory} × usage ${fac.usage}`}>{Math.round(c.score)}</span>
                </div>
              ) }) : <p className="muted">No documents matched — add rules to classify the estate.</p>}
            </div>
          </section>
        </>
      )}

      {tab === 'versions' && (
        <>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Version history &amp; audit</h3></div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Draft &amp; publish ontology changes; every publish is snapshotted with who &amp; when. Roll back restores that version's rules.</div>
            {(st.history || []).length ? st.history.map((h, i) => (
              <div className="ontver" key={i}><span className="ontvertag">v{h.v}</span><span className="ontverwhen">{h.at} · by {h.by}</span><span className="muted">{h.rules} rules · {h.labels} labels</span>{i > 0 && h.snap && <button className="ghost small" style={{ marginLeft: 'auto' }} onClick={() => rollback(h)} title="Restore this version's rules &amp; labels as a draft">↩ Roll back</button>}</div>
            )) : <p className="muted">No published versions yet — publish to create v{st.version}.</p>}
          </section>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>AI-assisted classification</h3><span className="ontprevtag">preview</span></div>
            <p className="muted" style={{ fontSize: 12 }}>Give the agent a few example documents per label; it learns to classify similar ones, with a confidence threshold and manual override. Requires the vision/LLM model — wired in the cloud build, mocked here.</p>
            <div className="ontexrow"><span className="ontchip">＋ add example docs</span><span className="muted">confidence ≥</span><input aria-label="Confidence threshold" type="range" min="50" max="99" defaultValue="80" disabled /><span className="muted">80%</span></div>
          </section>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Ontology relationships</h3><span className="ontprevtag">preview</span></div>
            <p className="muted" style={{ fontSize: 12 }}>Model dependencies for dependency-aware remediation &amp; reporting.</p>
            <div className="ontrels">
              {['Procedure supports Policy', 'Translation belongs to Original', 'Attachment belongs to Contract', 'Training Guide supersedes Legacy Manual'].map((r) => <span key={r} className="ontrel">{r}</span>)}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
