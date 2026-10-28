import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Library } from './StudyWorkspace'
import { Classroom, CoursePage } from './ClassroomWorkspace'
import { LessonOptions } from '../platform/actions'

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn() }))
vi.mock('../platform/api', () => mocks)
vi.mock('../platform/auth', () => ({ useAuth: () => ({ profile: { display_name: 'Fixture', privilege: 'student' } }) }))
beforeEach(() => {
  if (HTMLDialogElement.prototype.showModal) vi.spyOn(HTMLDialogElement.prototype, 'showModal').mockImplementation(function () { this.setAttribute('open', '') })
})
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.restoreAllMocks() })
const showCourse = () => render(<MemoryRouter initialEntries={['/classroom/c1']}><Routes><Route path="/classroom/:id" element={<CoursePage />} /><Route path="/classroom" element={<p>Classroom list route</p>} /></Routes></MemoryRouter>)

it('places lesson deletion in options and requires confirmation', async () => {
  let removed = false
  mocks.api.mockImplementation(async (path, options) => {
    if (options?.method === 'DELETE') { removed = true; return { deleted: true } }
    return path === '/api/lessons' && !removed ? [{ id: 'l1', title: 'Private fixture lesson', availability: 'ready', curriculum_id: 'v1' }] : []
  })
  render(<MemoryRouter><Library /></MemoryRouter>)
  fireEvent.click(await screen.findByLabelText('Options for Private fixture lesson'))
  fireEvent.click(screen.getByRole('button', { name: 'Delete lesson Private fixture lesson' }))
  let dialog = screen.getByRole('dialog')
  expect(removed).toBe(false)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(removed).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Delete lesson Private fixture lesson' }))
  dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Delete lesson' }))
  await screen.findByText('Your first learning path starts here')
  expect(mocks.api).toHaveBeenCalledWith('/api/lessons/l1', { method: 'DELETE' })
})

it('keeps the lesson and confirmation dialog visible when deletion fails', async () => {
  mocks.api.mockImplementation(async (path, options) => {
    if (options?.method === 'DELETE') throw new Error('A worker is updating this lesson. Please retry.')
    return path === '/api/lessons' ? [{ id: 'l1', title: 'Busy lesson', availability: 'planning' }] : []
  })
  render(<MemoryRouter><Library /></MemoryRouter>)
  fireEvent.click(await screen.findByLabelText('Options for Busy lesson'))
  fireEvent.click(screen.getByRole('button', { name: 'Delete lesson Busy lesson' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete lesson' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Please retry')
  expect(screen.getByRole('dialog')).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Busy lesson' })).toBeTruthy()
})

it('deletes the lesson ID rather than its curriculum version ID on a detail page', async () => {
  mocks.api.mockResolvedValue({ deleted: true })
  render(<LessonOptions lesson={{ id: 'version-1', lesson_id: 'lesson-1', title: 'Version fixture' }} />)
  fireEvent.click(screen.getByLabelText('Options for Version fixture'))
  fireEvent.click(screen.getByRole('button', { name: 'Delete lesson Version fixture' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete lesson' }))
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/api/lessons/lesson-1', { method: 'DELETE' }))
})

it('lets a learner leave from classroom options without an accidental single-click leave', async () => {
  let left = false
  mocks.api.mockImplementation(async () => left ? [] : [{ id: 'c1', title: 'Fixture class', role: 'student' }])
  mocks.post.mockImplementation(async () => { left = true; return { left: true } })
  render(<MemoryRouter><Classroom /></MemoryRouter>)
  fireEvent.click(await screen.findByLabelText('Options for Fixture class'))
  fireEvent.click(screen.getByRole('button', { name: 'Leave classroom Fixture class' }))
  expect(mocks.post).not.toHaveBeenCalled()
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Leave classroom' }))
  await screen.findByText('Your classroom belongs here')
  expect(mocks.post).toHaveBeenCalledWith('/api/courses/c1/leave')
})

it('shows the permanent code only in teacher settings and preserves it when enrollment is paused', async () => {
  let enabled = true
  mocks.api.mockImplementation(async (path, options) => {
    if (path === '/api/courses') return [{ id: 'c1', title: 'Teacher class', role: 'teacher' }]
    if (path === '/api/courses/c1/enrollment-code') {
      if (options?.method === 'DELETE') enabled = false
      return { code: 'fixture-permanent-code', enabled }
    }
    return []
  })
  mocks.post.mockImplementation(async () => { enabled = true; return { code: 'fixture-permanent-code', enabled } })
  showCourse()
  fireEvent.click(await screen.findByRole('button', { name: 'Settings' }))
  await screen.findByText('fixture-permanent-code')
  expect(screen.queryByRole('button', { name: /rotate/i })).toBeNull()
  expect(screen.queryByRole('button', { name: /Leave classroom/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Pause enrollment' }))
  await screen.findByRole('button', { name: 'Open enrollment' })
  expect(screen.getByText('fixture-permanent-code')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Open enrollment' }))
  await screen.findByRole('button', { name: 'Pause enrollment' })
  expect(screen.getByText('fixture-permanent-code')).toBeTruthy()
})

it('student settings show leave controls without requesting the enrollment code', async () => {
  mocks.api.mockImplementation(async path => path === '/api/courses' ? [{ id: 'c1', title: 'Student class', role: 'student' }] : [])
  mocks.post.mockResolvedValue({ left: true })
  showCourse()
  fireEvent.click(await screen.findByRole('button', { name: 'Settings' }))
  expect(screen.queryByText('Permanent class code')).toBeNull()
  expect(mocks.api.mock.calls.some(([path]) => path.endsWith('/enrollment-code'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Leave classroom Student class' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Leave classroom' }))
  await screen.findByText('Classroom list route')
})

it('teachers can revoke rejoining for a learner who left without forcibly restoring membership', async () => {
  mocks.api.mockImplementation(async (path, options) => {
    if (options?.method === 'PATCH') return { active: false }
    if (path === '/api/courses') return [{ id: 'c1', title: 'Teacher class', role: 'teacher' }]
    if (path.endsWith('/members')) return [{ id: 'm1', display_name: 'Former learner', active: false, left_voluntarily: true }]
    return []
  })
  showCourse()
  fireEvent.click(await screen.findByRole('button', { name: 'Members' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Revoke rejoining' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm revoke' }))
  await waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/api/courses/c1/members/m1?active=false', { method: 'PATCH' }))
})
