import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { SourceDetail } from './Independent'

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn() }))
vi.mock('../platform/api', () => mocks)
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('loads private source page access only on request and keeps extracted text editable', async () => {
  mocks.api.mockImplementation(async path => {
    if (path === '/api/sources/fixture-source') return { id: 'fixture-source', title: 'Fixture scan', kind: 'pdf', state: 'needs_confirmation', version: 1,
      evidence: [{ id: 'page-1', location: 'Page 1', method: 'fixture', text: 'Correct this uncertain symbol.', image_key: 'fixture-private-key', uncertainty: ['uncertain symbol'] }] }
    if (path === '/api/sources/fixture-source/evidence/page-1/image') return { url: 'https://media.fixture.test/page-1.png?fixture-signature=not-real' }
    throw new Error('Unexpected fixture request')
  })
  render(<MemoryRouter initialEntries={['/sources/fixture-source']}><Routes><Route path="/sources/:id" element={<SourceDetail />} /></Routes></MemoryRouter>)
  const button = await screen.findByRole('button', { name: 'Compare original page image' })
  expect(screen.queryByRole('img')).toBeNull()
  expect(mocks.api).toHaveBeenCalledTimes(1)
  fireEvent.click(button)
  const image = await screen.findByRole('img', { name: /Source reference for Page 1/ })
  expect(image.src).toContain('media.fixture.test/page-1.png')
  expect(mocks.api).toHaveBeenCalledWith('/api/sources/fixture-source/evidence/page-1/image')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Author corrected the source.' } })
  expect(screen.getByRole('textbox').value).toBe('Author corrected the source.')
  expect(screen.getByRole('button', { name: 'Confirm source for lessons' }).disabled).toBe(true)
})
