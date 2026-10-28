import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { NewLesson, SourceDetail, SourcesPage } from './Independent'

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn() }))
vi.mock('../platform/api', () => mocks)
vi.mock('../platform/auth', () => ({ useAuth: () => ({ config: { source_features: { text: true, youtube: true } } }) }))
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

it('removes a saved source only after confirmation and refreshes the list', async () => {
  let removed = false
  mocks.api.mockImplementation(async (path, options) => {
    if (options?.method === 'DELETE') { removed = true; return { deleted: true } }
    return removed ? [] : [{ id: 'source-a', title: 'Saved notes', state: 'needs_confirmation' }]
  })
  render(<MemoryRouter><SourcesPage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Remove source Saved notes' }))
  expect(removed).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Keep source' }))
  expect(removed).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Remove source Saved notes' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm removal' }))
  await screen.findByText('No sources yet')
  expect(mocks.api).toHaveBeenCalledWith('/api/sources/source-a', { method: 'DELETE' })
})

it('keeps a source visible and displays an in-use removal error', async () => {
  mocks.api.mockImplementation(async (path, options) => {
    if (options?.method === 'DELETE') throw new Error('Cancel the lesson preparation using this source before removing it.')
    return [{ id: 'source-a', title: 'In-use notes', state: 'confirmed' }]
  })
  render(<MemoryRouter><SourcesPage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Remove source In-use notes' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm removal' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Cancel the lesson preparation')
  expect(screen.getByRole('link', { name: /In-use notes/ })).toBeTruthy()
})

it('submits a YouTube source for extraction and opens its preview', async () => {
  mocks.api.mockResolvedValue([])
  mocks.post.mockResolvedValue({ id: 'video-source' })
  render(<MemoryRouter initialEntries={['/sources']}><Routes><Route path="/sources" element={<SourcesPage />} /><Route path="/sources/:id" element={<p>Video preview route</p>} /></Routes></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Source type'), { target: { value: 'youtube' } })
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Python video' } })
  fireEvent.change(screen.getByLabelText('Public video URL'), { target: { value: 'https://youtu.be/abcdefghijk' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create source preview' }))
  await screen.findByText('Video preview route')
  expect(mocks.post).toHaveBeenCalledWith('/api/sources', { kind: 'youtube', title: 'Python video', text: 'https://youtu.be/abcdefghijk' })
})

it('preselects the confirmed source passed to lesson planning', async () => {
  mocks.api.mockResolvedValue([{ id: 'video-source', title: 'Reviewed video', state: 'confirmed' }])
  mocks.post.mockResolvedValue({ job_id: 'plan-job' })
  render(<MemoryRouter initialEntries={['/lessons/new?source=video-source']}><NewLesson /></MemoryRouter>)
  const source = await screen.findByRole('checkbox', { name: 'Reviewed video' })
  expect(source.checked).toBe(true)
  fireEvent.change(screen.getByLabelText('Lesson title'), { target: { value: 'Video lesson' } })
  fireEvent.change(screen.getByLabelText('Your learning goal'), { target: { value: 'Understand the concepts in the video.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Plan the full curriculum' }))
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/api/lessons', {
    title: 'Video lesson', goal: 'Understand the concepts in the video.', source_ids: ['video-source'], course_id: null,
  }))
})

it('excludes a removed attachment from the submitted quick lesson', async () => {
  mocks.api.mockResolvedValue({ job_id: 'quick-job' })
  render(<MemoryRouter><NewLesson /></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'Python loops' } })
  fireEvent.change(screen.getByLabelText('What should you be able to do afterwards?'), { target: { value: 'Understand how Python loops work.' } })
  const first = new File(['fixture'], 'first.pdf', { type: 'application/pdf' })
  const second = new File(['fixture'], 'second.pdf', { type: 'application/pdf' })
  fireEvent.change(screen.getByLabelText(/Slides or documents/), { target: { files: [first, second] } })
  fireEvent.click(screen.getByRole('button', { name: 'Remove file first.pdf' }))
  expect(screen.queryByRole('button', { name: 'Remove file first.pdf' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Build my lesson' }))
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/api/lessons/quick', expect.objectContaining({ method: 'POST' })))
  expect(mocks.api.mock.calls.find(([path]) => path === '/api/lessons/quick')[1].body.getAll('files').map(f => f.name)).toEqual(['second.pdf'])
})

it('searches sources and distinguishes failed extraction from review', async () => {
  mocks.api.mockResolvedValue([
    { id: 'ready', title: 'Loop notes', kind: 'text', state: 'confirmed' },
    { id: 'failed', title: 'Video lecture', kind: 'youtube', state: 'pending', job_state: 'failed' },
    { id: 'review', title: 'Loop slides', kind: 'pptx', state: 'needs_confirmation' },
  ])
  render(<MemoryRouter><SourcesPage /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Video lecture' })
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'attention' } })
  expect(screen.getByRole('link', { name: 'Resolve extraction' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: 'Loop notes' })).toBeNull()
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'all' } })
  fireEvent.change(screen.getByLabelText('Search sources'), { target: { value: 'slides' } })
  expect(screen.getByRole('link', { name: 'Loop slides' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: 'Video lecture' })).toBeNull()
})

it('combines confirmed sources while keeping unreviewed sources unselectable', async () => {
  mocks.api.mockResolvedValue([
    { id: 'a', title: 'Reviewed notes', state: 'confirmed' },
    { id: 'b', title: 'Reviewed video', state: 'confirmed' },
    { id: 'c', title: 'Unreviewed slides', state: 'needs_confirmation' },
  ])
  render(<MemoryRouter><SourcesPage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Select Reviewed notes for a lesson' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select Reviewed video for a lesson' }))
  const target = new URL(screen.getByRole('link', { name: 'Create lesson from selection' }).href)
  expect(target.searchParams.getAll('source')).toEqual(['a', 'b'])
  expect(screen.queryByRole('checkbox', { name: /Unreviewed slides/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))
  expect(screen.queryByRole('link', { name: 'Create lesson from selection' })).toBeNull()
})

it('preselects multiple source IDs in the lesson planner', async () => {
  mocks.api.mockResolvedValue([{ id: 'a', title: 'Source A', state: 'confirmed' }, { id: 'b', title: 'Source B', state: 'confirmed' }])
  render(<MemoryRouter initialEntries={['/lessons/new?source=a&source=b']}><NewLesson /></MemoryRouter>)
  expect((await screen.findByRole('checkbox', { name: 'Source A' })).checked).toBe(true)
  expect(screen.getByRole('checkbox', { name: 'Source B' }).checked).toBe(true)
})

it('stages uploaded files for review before sending them to the server', async () => {
  mocks.api.mockResolvedValue([])
  render(<MemoryRouter><SourcesPage /></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Source type'), { target: { value: 'upload' } })
  // This fixture deliberately has no enabled upload infrastructure.
  expect(screen.getByRole('button', { name: 'Create source preview' }).disabled).toBe(true)
  expect(screen.getByLabelText('Source file').disabled).toBe(true)
  expect(mocks.api.mock.calls.every(([path]) => path === '/api/sources')).toBe(true)
})

it('requires edited confirmed material to be saved and confirmed before creating a lesson', async () => {
  const source = { id: 'source-a', title: 'Confirmed notes', kind: 'text', state: 'confirmed', version: 1, confirmed: true,
    evidence: [{ id: 'text-1', location: 'Notes', method: 'typed', text: 'The original source explanation.', uncertainty: [] }] }
  mocks.api.mockImplementation(async (path, options) => {
    if (options?.method === 'PUT') return { ...source, version: 2, evidence: JSON.parse(options.body).evidence }
    return source
  })
  render(<MemoryRouter initialEntries={['/sources/source-a']}><Routes><Route path="/sources/:id" element={<SourceDetail />} /></Routes></MemoryRouter>)
  await screen.findByRole('link', { name: /Use in a lesson/ })
  fireEvent.change(screen.getByLabelText('Extracted text for Notes'), { target: { value: 'Corrected source explanation.' } })
  expect(screen.queryByRole('link', { name: /Use in a lesson/ })).toBeNull()
  expect(screen.getByText('Unsaved changes')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Confirm source for lessons' }))
  await screen.findByRole('link', { name: /Use in a lesson/ })
  expect(screen.getByLabelText('Extracted text for Notes').value).toBe('Corrected source explanation.')
  expect(mocks.api).toHaveBeenCalledWith('/api/sources/source-a/preview', expect.objectContaining({ method: 'PUT' }))
})
