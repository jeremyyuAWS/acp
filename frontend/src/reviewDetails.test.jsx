import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import ReviewDetails from './ReviewDetails.jsx'
it('collapses secondary review details with native keyboard-accessible disclosure', () => {
  const wrapper = document.createElement('div')
  wrapper.innerHTML = renderToStaticMarkup(createElement(ReviewDetails, null, createElement('input', { 'aria-label': 'Due date' })))
  expect(wrapper.querySelector('details').open).toBe(false)
  expect(wrapper.querySelector('summary').textContent).toBe('Audit trail, due date and comments')
  expect(wrapper.querySelector('input')).not.toBeNull()
})
