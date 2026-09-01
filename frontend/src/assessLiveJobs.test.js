import { describe, expect, it } from 'vitest'
import { activeAssessmentFiles, assessmentStageLabel } from './assessLiveJobs.js'

describe('active assessment files', () => {
  it('combines running file jobs across worker replicas for the selected scan', () => {
    const jobs = [
      { scan_id: 's1', type: 'scan_file', status: 'running', phase: 'analyse.ocr',
        payload: JSON.stringify({ file: 'one.pdf' }) },
      { scan_id: 's1', type: 'scan_file', status: 'running', phase: 'analyse.structure',
        payload: JSON.stringify({ file: 'two.docx' }) },
      { scan_id: 'other', type: 'scan_file', status: 'running', payload: '{"file":"private.pdf"}' },
      { scan_id: 's1', type: 'scan_file', status: 'queued', payload: '{"file":"waiting.pdf"}' },
    ]
    const active = activeAssessmentFiles(jobs, 's1')
    expect([...active]).toEqual([
      ['one.pdf', 'Reading text and images'],
      ['two.docx', 'Checking document structure'],
    ])
  })

  it('uses honest stage wording and never invents a percentage', () => {
    expect(assessmentStageLabel()).toBe('Assessing now')
    expect(assessmentStageLabel('analyse.pdf')).toBe('Opening PDF structure')
  })
})
