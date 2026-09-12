import {readFileSync} from 'node:fs'
import {expect, it} from 'vitest'
import RetiredAssessmentDetails from './RetiredReleaseAssessmentDetails.jsx'
import {RetiredReleaseUnavailableFiles} from './ReleaseQuickActions.jsx'

it('keeps the removed Release panels available without mounting them', () => {
  const publish = readFileSync('src/Publish.jsx', 'utf8')
  const quick = readFileSync('src/ReleaseQuickActions.jsx', 'utf8')
  expect(typeof RetiredAssessmentDetails).toBe('function')
  expect(typeof RetiredReleaseUnavailableFiles).toBe('function')
  expect(publish).not.toContain('RemediationLiveDocuments')
  expect(publish).not.toContain('<RetiredReleaseAssessmentDetails')
  expect(quick).not.toContain('<RetiredReleaseUnavailableFiles')
})
