import { it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import DiscoverRunProgress from './DiscoverRunProgress.jsx'

it('shows real folder enumeration progress without inventing full/delta enumeration', () => {
 const html=renderToStaticMarkup(createElement(DiscoverRunProgress,{busy:true,source:'sharepoint',scope:{kind:'sharepoint',folders:[{id:'picked',name:'Clinical'}]},progress:{phase:'discovering',files_found:12,folders_visited:3,freshness:'checkpoint'}}))
 expect(html).toContain('Reading selected folders')
 expect(html).not.toContain('Enumeration starting')
 expect(html).not.toContain('Full enumeration')
 expect(html).toContain('Showing latest checkpoint')
})
it('the canonical cross-tab card carries the same measured freshness as Discover', () => {
 const app=readFileSync('src/App.jsx','utf8')
 const mount=app.slice(app.indexOf('<DiscoverRunProgress progress={progress}'),app.indexOf('assess: canonicalStage?',app.indexOf('<DiscoverRunProgress progress={progress}')))
 expect(mount).toContain('freshness={progress?.freshness ?? null}')
})
