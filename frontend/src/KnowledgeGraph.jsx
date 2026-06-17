import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'

const CRIT = {
  SC_1_1_1: ['1.1.1', 'non-text content'], SC_1_3_1: ['1.3.1', 'info & relationships'],
  SC_1_3_2: ['1.3.2', 'meaningful sequence'], SC_1_4_3: ['1.4.3', 'contrast'],
  SC_2_2_2: ['2.2.2', 'pause, stop, hide'], SC_2_4_2: ['2.4.2', 'page titled'],
  SC_2_4_4: ['2.4.4', 'link purpose'], SC_3_1_1: ['3.1.1', 'language of page'],
  SC_3_1_2: ['3.1.2', 'language of parts'], SC_4_1_2: ['4.1.2', 'name, role, value'],
}
const fileColor = (d) => (d.status === 'error' ? '#888780' : d.compliant ? '#639922' : '#EF9F27')

export default function KnowledgeGraph({ files }) {
  const ref = useRef(null)
  const [detail, setDetail] = useState(null)

  useEffect(() => {
    if (!files?.length || !ref.current) return

    const cnt = {}
    files.forEach((f) => new Set(f.issues.map((i) => i.wcag)).forEach((c) => { cnt[c] = (cnt[c] || 0) + 1 }))
    const nodes = []
    Object.keys(cnt).forEach((c) => nodes.push({ id: c, t: 'crit', label: (CRIT[c]?.[0] ?? c), name: (CRIT[c]?.[1] ?? c), n: cnt[c] }))
    files.forEach((f) => nodes.push({
      id: f.file, t: 'file', status: f.status, score: f.score, compliant: f.compliant,
      fails: [...new Set(f.issues.map((i) => i.wcag))],
    }))
    const links = []
    const adj = {}
    const tie = (a, b) => { (adj[a] ??= new Set([a])).add(b); (adj[b] ??= new Set([b])).add(a) }
    files.forEach((f) => [...new Set(f.issues.map((i) => i.wcag))].forEach((c) => { links.push({ source: f.file, target: c }); tie(f.file, c) }))

    const W = 860, H = 470
    const crad = (d) => 12 + d.n * 2.6
    const frad = (d) => (d.status === 'error' ? 6 : 8)

    const svg = d3.select(ref.current)
    svg.selectAll('*').remove()
    svg.attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%')

    const link = svg.append('g').attr('stroke', 'rgba(70,48,63,0.18)')
      .selectAll('line').data(links).join('line').attr('stroke-width', 1.3)
    const node = svg.append('g').selectAll('g').data(nodes).join('g').style('cursor', 'pointer')

    // pulsing halo on the most-failed criterion
    const big = nodes.filter((n) => n.t === 'crit').sort((a, b) => b.n - a.n)[0]
    if (big) {
      const halo = node.filter((d) => d === big).insert('circle', ':first-child')
        .attr('r', crad(big)).attr('fill', 'none').attr('stroke', '#F0524A').attr('stroke-width', 2).attr('opacity', 0.55)
      const mk = (attr, vals) => {
        const a = document.createElementNS('http://www.w3.org/2000/svg', 'animate')
        a.setAttribute('attributeName', attr); a.setAttribute('values', vals)
        a.setAttribute('dur', '2.2s'); a.setAttribute('repeatCount', 'indefinite')
        return a
      }
      halo.node().append(mk('r', `${crad(big)};${crad(big) + 13};${crad(big)}`), mk('opacity', '0.55;0;0.55'))
    }

    node.append('circle')
      .attr('r', (d) => (d.t === 'crit' ? crad(d) : frad(d)))
      .attr('fill', (d) => (d.t === 'crit' ? '#F0524A' : fileColor(d)))
      .attr('stroke', '#fff').attr('stroke-width', 1.5)
    node.append('title').text((d) => (d.t === 'crit' ? `WCAG ${d.label} — ${d.name}` : d.id))
    node.filter((d) => d.t === 'crit').append('text')
      .text((d) => d.label).attr('text-anchor', 'middle').attr('dy', (d) => -crad(d) - 5)
      .attr('font-size', '11px').attr('font-weight', 600).attr('fill', '#993C1D')

    node.on('mouseover', (e, d) => {
      const near = adj[d.id] ?? new Set([d.id])
      node.style('opacity', (n) => (near.has(n.id) ? 1 : 0.12))
      link.style('stroke-opacity', (l) => (l.source.id === d.id || l.target.id === d.id ? 0.95 : 0.05))
    }).on('mouseout', () => { node.style('opacity', 1); link.style('stroke-opacity', 1) })

    node.on('click', (e, d) => {
      if (d.t === 'file') {
        setDetail({
          kind: 'file', title: d.id,
          status: d.status === 'error' ? 'unanalysable' : d.compliant ? 'certifiable' : 'has issues',
          score: d.score, fails: d.fails.map((c) => CRIT[c]?.[0] ?? c),
        })
      } else {
        setDetail({
          kind: 'crit', title: `WCAG ${d.label} — ${d.name}`, count: d.n,
          fns: files.filter((f) => f.issues.some((i) => i.wcag === d.id)).map((f) => f.file),
        })
      }
    })

    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id((d) => d.id).distance(60).strength(0.55))
      .force('charge', d3.forceManyBody().strength(-180))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide((d) => (d.t === 'crit' ? crad(d) : frad(d)) + 7))
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
  }, [files])

  return (
    <div className="panel">
      <div className="kglegend">
        <span><i style={{ background: '#639922' }} />certifiable</span>
        <span><i style={{ background: '#EF9F27' }} />has issues</span>
        <span><i style={{ background: '#888780' }} />unanalysable</span>
        <span><i style={{ background: '#F0524A' }} />WCAG criterion failed</span>
        <span className="muted">hover to isolate · drag to rearrange</span>
      </div>
      <svg ref={ref} role="img" aria-label="Force-directed graph of files linked to the WCAG criteria they fail" />
      <div className="kgdetail">
        {!detail && <span className="muted">Click a node — files cluster around the criteria they share.</span>}
        {detail?.kind === 'file' && (
          <span><b>{detail.title}</b> · {detail.status} · score {detail.score ?? 'n/a'}<br />
            <span className="muted">fails: {detail.fails.length ? detail.fails.join(', ') : (detail.status === 'unanalysable' ? 'could not analyse' : 'none — compliant')}</span></span>
        )}
        {detail?.kind === 'crit' && (
          <span><b style={{ color: '#993C1D' }}>{detail.title}</b> · {detail.count} files<br />
            <span className="muted">{detail.fns.join(', ')}</span></span>
        )}
      </div>
    </div>
  )
}
