import { useEffect, useRef, useState, useMemo } from 'react'
import * as d3 from 'd3'
import FileDrawer from './FileDrawer.jsx'

const CRIT = {
  SC_1_1_1: ['1.1.1', 'non-text content'], SC_1_3_1: ['1.3.1', 'info & relationships'],
  SC_1_3_2: ['1.3.2', 'meaningful sequence'], SC_1_4_3: ['1.4.3', 'contrast'],
  SC_2_2_2: ['2.2.2', 'pause, stop, hide'], SC_2_4_2: ['2.4.2', 'page titled'],
  SC_2_4_4: ['2.4.4', 'link purpose'], SC_3_1_1: ['3.1.1', 'language of page'],
  SC_3_1_2: ['3.1.2', 'language of parts'], SC_4_1_2: ['4.1.2', 'name, role, value'],
  SC_1_2_1: ['1.2.1', 'audio/video transcript'], SC_1_2_2: ['1.2.2', 'captions'],
  SC_1_2_3: ['1.2.3', 'audio description / alt'], SC_1_2_5: ['1.2.5', 'audio description'],
}
const fileColor = (d) => (d.status === 'error' ? '#888780' : d.compliant ? '#639922' : '#EF9F27')

// Cap the graph to the highest-priority documents so it stays readable at scale.
const LIMIT = 45
const SR_W = { Executive: 3, Director: 2, Manager: 1, Staff: 0 }
const priority = (f) => {
  const tags = f.tags || []
  return (tags.includes('public-facing') ? 3 : 0) + (tags.includes('high-traffic') ? 2 : 0) + (SR_W[f.seniority] || 0)
    + (f.issues || []).filter((i) => i.severity === 'CRITICAL').length * 2 + (f.issues || []).filter((i) => i.severity === 'SERIOUS').length
}

export default function KnowledgeGraph({ files }) {
  const ref = useRef(null)
  const [detail, setDetail] = useState(null)
  const [dept, setDept] = useState('')
  const [showClean, setShowClean] = useState(false)
  const [focusCrit, setFocusCrit] = useState(null)
  const [selFile, setSelFile] = useState(null)
  const [showAll, setShowAll] = useState(false)
  const [query, setQuery] = useState('')
  const [dq, setDq] = useState('') // debounced, lower-cased — drives filtering without rebuilding the sim every keystroke
  useEffect(() => { const t = setTimeout(() => setDq(query.trim().toLowerCase()), 180); return () => clearTimeout(t) }, [query])

  const depts = useMemo(() => [...new Set(files.map((f) => f.department).filter(Boolean))], [files])
  const { graphFiles, total } = useMemo(() => {
    let s = dept ? files.filter((f) => f.department === dept) : files
    if (!showClean) s = s.filter((f) => (f.issues || []).length) // only failing files are linked
    if (focusCrit) s = s.filter((f) => (f.issues || []).some((i) => i.wcag === focusCrit))
    if (dq) s = s.filter((f) => [f.file, f.owner, f.department, f.sourceName, f.type].some((v) => (v || '').toLowerCase().includes(dq)))
    const t = s.length
    // a search bypasses the priority cap, so a matching doc is never hidden by it
    if (!showAll && !focusCrit && !dq && t > LIMIT) s = [...s].sort((a, b) => priority(b) - priority(a)).slice(0, LIMIT)
    return { graphFiles: s, total: t }
  }, [files, dept, showClean, focusCrit, showAll, dq])
  const capped = graphFiles.length < total

  useEffect(() => {
    if (!ref.current) return
    const svg = d3.select(ref.current)
    svg.selectAll('*').remove()
    if (!graphFiles.length) return

    const cnt = {}
    graphFiles.forEach((f) => new Set(f.issues.map((i) => i.wcag)).forEach((c) => { cnt[c] = (cnt[c] || 0) + 1 }))
    const nodes = []
    Object.keys(cnt).forEach((c) => nodes.push({ id: c, t: 'crit', label: (CRIT[c]?.[0] ?? c), name: (CRIT[c]?.[1] ?? c), n: cnt[c] }))
    graphFiles.forEach((f) => nodes.push({ id: f.file, t: 'file', f, status: f.status, score: f.score, compliant: f.compliant, fails: [...new Set(f.issues.map((i) => i.wcag))] }))
    const links = []
    const adj = {}
    const tie = (a, b) => { (adj[a] ??= new Set([a])).add(b); (adj[b] ??= new Set([b])).add(a) }
    graphFiles.forEach((f) => [...new Set(f.issues.map((i) => i.wcag))].forEach((c) => { links.push({ source: f.file, target: c }); tie(f.file, c) }))

    const W = 860, H = 520
    const maxN = d3.max(nodes, (n) => (n.t === 'crit' ? n.n : 0)) || 1
    const rscale = d3.scaleSqrt().domain([1, maxN]).range([11, 30])
    const crad = (d) => rscale(d.n)
    const frad = (d) => (d.status === 'error' ? 5 : 7)

    svg.attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%')
    const link = svg.append('g').attr('stroke', 'rgba(70,48,63,0.18)').selectAll('line').data(links).join('line').attr('stroke-width', 1.3)
    const node = svg.append('g').selectAll('g').data(nodes).join('g').style('cursor', 'pointer')

    const big = nodes.filter((n) => n.t === 'crit').sort((a, b) => b.n - a.n)[0]
    if (big && !focusCrit) {
      const halo = node.filter((d) => d === big).insert('circle', ':first-child')
        .attr('r', crad(big)).attr('fill', 'none').attr('stroke', '#F0524A').attr('stroke-width', 2).attr('opacity', 0.55)
      const mk = (attr, vals) => { const a = document.createElementNS('http://www.w3.org/2000/svg', 'animate'); a.setAttribute('attributeName', attr); a.setAttribute('values', vals); a.setAttribute('dur', '2.2s'); a.setAttribute('repeatCount', 'indefinite'); return a }
      halo.node().append(mk('r', `${crad(big)};${crad(big) + 13};${crad(big)}`), mk('opacity', '0.55;0;0.55'))
    }

    node.append('circle')
      .attr('r', (d) => (d.t === 'crit' ? crad(d) : frad(d)))
      .attr('fill', (d) => (d.t === 'crit' ? '#F0524A' : fileColor(d)))
      .attr('stroke', '#fff').attr('stroke-width', 1.5)
    node.append('title').text((d) => (d.t === 'crit' ? `WCAG ${d.label} — ${d.name} · ${d.n} files · click to focus` : `${d.id} · click for details`))
    node.filter((d) => d.t === 'crit').append('text')
      .text((d) => d.label).attr('text-anchor', 'middle').attr('dy', (d) => -crad(d) - 5)
      .attr('font-size', '11px').attr('font-weight', 600).attr('fill', '#993C1D')

    const isolate = (d) => {
      const near = adj[d.id] ?? new Set([d.id])
      node.style('opacity', (n) => (near.has(n.id) ? 1 : 0.12))
      link.style('stroke-opacity', (l) => (l.source.id === d.id || l.target.id === d.id ? 0.95 : 0.05))
    }
    const restore = () => { node.style('opacity', 1); link.style('stroke-opacity', 1) }
    const activate = (d) => {
      if (d.t === 'file') { setSelFile(d.f) } else {
        setFocusCrit((prev) => (prev === d.id ? null : d.id))
        setDetail({ kind: 'crit', title: `WCAG ${d.label} — ${d.name}`, count: d.n, fns: graphFiles.filter((f) => f.issues.some((i) => i.wcag === d.id)).map((f) => f.file).slice(0, 30) })
      }
    }

    // Keyboard a11y: each node is a focusable button with a roving tabindex (only the
    // active node is in the tab order). Arrow keys move between nodes, Enter/Space opens,
    // Escape clears the isolate. Focus mirrors the hover-isolate so keyboard users get the
    // same "what connects to this" highlight that mouse users get.
    node.attr('class', 'kgnode').attr('role', 'button').attr('tabindex', (d, i) => (i === 0 ? 0 : -1))
      .attr('aria-label', (d) => (d.t === 'crit'
        ? `WCAG ${d.label}, ${d.name}. ${d.n} document${d.n === 1 ? '' : 's'} fail this criterion. Press Enter to focus the graph on them.`
        : `${d.id}. ${d.compliant ? 'Certifiable document' : d.status === 'error' ? 'Unanalysable document' : 'Document with open findings'}. Press Enter for details.`))
    const els = node.nodes()
    const focusAt = (i) => { const j = ((i % els.length) + els.length) % els.length; els.forEach((el, k) => el.setAttribute('tabindex', k === j ? '0' : '-1')); els[j].focus() }

    node.on('mouseover', (e, d) => isolate(d)).on('mouseout', restore)
    node.on('focus', (e, d) => isolate(d)).on('blur', restore)
    node.on('click', (e, d) => activate(d))
    node.on('keydown', (e, d) => {
      const i = els.indexOf(e.currentTarget)
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(d) }
      else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); focusAt(i + 1) }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); focusAt(i - 1) }
      else if (e.key === 'Escape') { e.preventDefault(); e.currentTarget.blur(); restore() }
    })

    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id((d) => d.id).distance(74).strength(0.45))
      .force('charge', d3.forceManyBody().strength(-265))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('x', d3.forceX(W / 2).strength(0.05))
      .force('y', d3.forceY(H / 2).strength(0.07))
      .force('collide', d3.forceCollide((d) => (d.t === 'crit' ? crad(d) : frad(d)) + 9))
      .on('tick', () => {
        nodes.forEach((d) => { d.x = Math.max(14, Math.min(W - 14, d.x)); d.y = Math.max(16, Math.min(H - 14, d.y)) })
        link.attr('x1', (d) => d.source.x).attr('y1', (d) => d.source.y).attr('x2', (d) => d.target.x).attr('y2', (d) => d.target.y)
        node.attr('transform', (d) => `translate(${d.x},${d.y})`)
      })
    node.call(d3.drag()
      .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
      .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null }))

    return () => sim.stop()
  }, [graphFiles, focusCrit])

  return (
    <div className="panel">
      <div className="kgcontrols">
        <div className="kgsearch">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search documents, owners, sources…" aria-label="Search the knowledge graph" />
          {query && <button type="button" className="kgsearchx" aria-label="Clear search" onClick={() => setQuery('')}>✕</button>}
        </div>
        <select value={dept} onChange={(e) => { setDept(e.target.value); setFocusCrit(null) }} aria-label="Filter the graph by department">
          <option value="">All departments</option>
          {depts.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <button className={showClean ? 'fchip on' : 'fchip'} onClick={() => setShowClean((s) => !s)}>show compliant</button>
        {capped && !dq && <button className="fchip" onClick={() => setShowAll(true)}>show all {total}</button>}
        {showAll && !focusCrit && <button className="fchip on" onClick={() => setShowAll(false)}>top priority only ✕</button>}
        {focusCrit && <button className="fchip on" onClick={() => { setFocusCrit(null); setDetail(null) }}>focused: WCAG {CRIT[focusCrit]?.[0] ?? focusCrit} ✕</button>}
        <span className="muted" style={{ marginLeft: 'auto' }}>{dq ? `${graphFiles.length} match${graphFiles.length === 1 ? '' : 'es'} for “${query.trim()}”` : capped ? `top ${graphFiles.length} of ${total} by priority` : `${graphFiles.length} document(s)`} · click a criterion to focus</span>
      </div>
      <div className="kglegend">
        <span><i style={{ background: '#EF9F27' }} />has issues</span>
        {showClean && <span><i style={{ background: '#639922' }} />certifiable</span>}
        {showClean && <span><i style={{ background: '#888780' }} />unanalysable</span>}
        <span><i style={{ background: '#F0524A' }} />WCAG criterion failed</span>
        <span className="muted">hover or focus to isolate · arrow keys to navigate · enter to open</span>
      </div>
      {graphFiles.length === 0
        ? <p className="muted" style={{ padding: '40px 0', textAlign: 'center' }}>No documents match{dq ? ` “${query.trim()}”` : ''} — {dq ? 'try a different search, ' : 'try a different '}department{dq ? '' : ''} or enable “show compliant”.</p>
        : <svg ref={ref} role="group" aria-label="Force-directed graph of documents linked to the WCAG criteria they fail. Tab into the graph, use the arrow keys to move between nodes, and press Enter to open a node." />}
      <div className="kgdetail">
        {!detail && <span className="muted">Click a criterion to focus the graph on its documents, or a document to open its details.</span>}
        {detail?.kind === 'crit' && (
          <span><b style={{ color: '#993C1D' }}>{detail.title}</b> · {detail.count} document(s)<br />
            <span className="muted">{detail.fns.join(', ')}{detail.count > 30 ? ' …' : ''}</span></span>
        )}
      </div>
      {selFile && <FileDrawer file={selFile} onClose={() => setSelFile(null)} />}
    </div>
  )
}
