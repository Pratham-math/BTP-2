import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { Library } from './StudyWorkspace'
import { Classroom, CoursePage } from './ClassroomWorkspace'
import { JobEta } from '../platform/common'

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), profile: { display_name: 'Learner', privilege: 'student' } }))
vi.mock('../platform/api', () => ({ api: mocks.api, post: mocks.post }))
vi.mock('../platform/auth', () => ({ useAuth: () => ({ profile: mocks.profile }) }))
afterEach(() => { cleanup(); vi.resetAllMocks(); mocks.profile.privilege = 'student' })

function coursePage() { render(<MemoryRouter initialEntries={['/classroom/c1']}><Routes><Route path="/classroom/:id" element={<CoursePage />} /></Routes></MemoryRouter>) }

it('keeps classroom sessions and jobs out of the independent workspace', async () => {
  mocks.api.mockImplementation(async path => ({
    '/api/lessons': [{ id: 'l1', title: 'Private loops', course_id: null, curriculum_id: 'v1', availability: 'ready' }, { id: 'l2', title: 'Classroom lesson', course_id: 'c1', availability: 'ready' }],
    '/api/sessions': [{ id: 's1', title: 'Private loops', course_id: null, curriculum_id: 'v1', state: 'checkpoint', total_objectives: 3, covered_objectives: 1 }, { id: 's2', title: 'Classroom session', course_id: 'c1', state: 'checkpoint' }],
    '/api/jobs': [{ id: 'j1', title: 'Classroom preparation', lesson_id: 'l2', course_id: 'c1', kind: 'quick_lesson', state: 'running', stage: 'author' }],
  }[path]))
  render(<MemoryRouter><Library /></MemoryRouter>)
  expect((await screen.findByRole('link', { name: /Resume lesson/ })).getAttribute('href')).toBe('/learn/s1')
  expect(screen.queryByText('Classroom session')).toBeNull()
  expect(screen.queryByText('Classroom lesson')).toBeNull()
  expect(screen.queryByText('Classroom preparation')).toBeNull()
  fireEvent.change(screen.getByLabelText('Search lessons'), { target: { value: 'unknown topic' } })
  expect(screen.getByText('No matching lessons')).toBeTruthy()
})

it('resumes a student assignment and never loads teacher-only data', async () => {
  mocks.api.mockImplementation(async path => ({
    '/api/courses': [{ id: 'c1', title: 'Python class', role: 'student' }],
    '/api/courses/c1/assignments': [{ id: 'a1', title: 'Loop assignment', curriculum_id: 'v1' }],
    '/api/sessions': [{ id: 's1', title: 'Loop assignment', course_id: 'c1', assignment_id: 'a1', state: 'checkpoint', total_objectives: 3, covered_objectives: 1, passed_objectives: 1 }],
  }[path]))
  coursePage()
  expect((await screen.findByRole('link', { name: /Resume assignment/ })).getAttribute('href')).toBe('/learn/s1')
  expect(screen.getByText('1 of 3 objectives covered · 1 passed independently')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Members' })).toBeNull()
  expect(mocks.api.mock.calls.some(([path]) => path.includes('/members') || path.includes('/reports') || path === '/api/lessons' || path === '/api/jobs')).toBe(false)
})

it('makes a teacher confirm membership revocation and shows published version links', async () => {
  mocks.profile.privilege = 'teacher'
  mocks.api.mockImplementation(async (path, options) => {
    if (options?.method === 'PATCH') return { active: false }
    return {
      '/api/courses': [{ id: 'c1', title: 'Python class', role: 'teacher' }],
      '/api/courses/c1/assignments': [{ id: 'a1', title: 'Published loops', curriculum_id: 'v1' }],
      '/api/lessons': [], '/api/jobs': [],
      '/api/courses/c1/members': [{ id: 'm1', display_name: 'Fixture learner', active: true }],
    }[path]
  })
  coursePage()
  expect((await screen.findByRole('link', { name: 'Open assigned version' })).getAttribute('href')).toBe('/reviews/v1')
  expect(screen.queryByRole('button', { name: /Start assignment/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Members' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Revoke' }))
  expect(mocks.api.mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Confirm revoke' }))
  await screen.findByText('Classroom access revoked.')
  expect(mocks.api).toHaveBeenCalledWith('/api/courses/c1/members/m1?active=false', { method: 'PATCH' })
})

it('students can join but cannot create classrooms', async () => {
  mocks.api.mockResolvedValue([])
  mocks.post.mockRejectedValue(new Error('Enrollment code is invalid.'))
  render(<MemoryRouter><Classroom /></MemoryRouter>)
  await screen.findByText('Your classroom belongs here')
  expect(screen.queryByRole('button', { name: 'Create course' })).toBeNull()
  fireEvent.change(screen.getByLabelText('Enrollment code'), { target: { value: 'fixture-invalid-code' } })
  fireEvent.click(screen.getByRole('button', { name: 'Join classroom' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Enrollment code is invalid.')
})

it('labels initial ETA ranges and excludes queue waiting', () => {
  render(<JobEta eta={{ status: 'queued', basis: 'rough_initial_range', lower_seconds: 600, upper_seconds: 2400, target: 'first playable lesson block' }} />)
  expect(screen.getByText(/10 min–40 min/)).toBeTruthy()
  expect(screen.getByText(/queue wait is additional/)).toBeTruthy()
  expect(screen.getByText(/Rough initial range/)).toBeTruthy()
})

it('stops the countdown on an overrun or a paused job', () => {
  const { rerender } = render(<JobEta eta={{ status: 'taking_longer' }} />)
  expect(screen.getByText(/Taking longer than estimated/)).toBeTruthy()
  rerender(<JobEta eta={{ status: 'waiting_for_input', upper_seconds: 99 }} />)
  expect(screen.queryByText(/time remaining/)).toBeNull()
  expect(screen.getByText(/Waiting for your attention/)).toBeTruthy()
  rerender(<JobEta eta={{ status: 'completed', upper_seconds: 99 }} />)
  expect(screen.queryByText(/Estimated/)).toBeNull()
})
