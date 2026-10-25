import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Account } from './Account'

const mocks = vi.hoisted(() => ({ post: vi.fn(), signOut: vi.fn() }))
vi.mock('../platform/auth', () => ({ useAuth: () => ({ profile: { display_name: 'Fixture learner', email: 'fixture@example.test', privilege: 'student' }, signOut: mocks.signOut }) }))
vi.mock('../platform/api', () => ({ post: mocks.post, api: vi.fn() }))
afterEach(cleanup)
beforeEach(() => vi.clearAllMocks())

it('requires explicit typed confirmation before enabling an erasure request', () => {
  render(<Account />)
  expect(screen.getByRole('button', { name: 'Disable account and request deletion' }).disabled).toBe(true)
  fireEvent.change(screen.getByRole('textbox', { name: 'Type DELETE to confirm' }), { target: { value: 'DELETE' } })
  expect(screen.getByRole('button', { name: 'Disable account and request deletion' }).disabled).toBe(false)
  expect(mocks.post).not.toHaveBeenCalled()
})

it('shows a pending cleanup receipt without claiming that all copies are erased', async () => {
  mocks.post.mockResolvedValue({ job_id: 'fixture-erasure-job', message: 'Cleanup queued; account access disabled.' })
  render(<Account />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DELETE' } })
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Disable account and request deletion' })))
  expect(mocks.post).toHaveBeenCalledWith('/api/me/erasure', { confirmation: 'DELETE' })
  expect(screen.getByText(/does not confirm that all copies/)).toBeTruthy()
  expect(screen.getByText('Request reference: fixture-erasure-job')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Finish and sign out' }))
  expect(mocks.signOut).toHaveBeenCalledOnce()
})

it('keeps the confirmation form usable if the request is rejected', async () => {
  mocks.post.mockRejectedValue(new Error('Assign another administrator first.'))
  render(<Account />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DELETE' } })
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Disable account and request deletion' })))
  expect(screen.getByRole('alert').textContent).toBe('Assign another administrator first.')
  expect(screen.getByRole('button', { name: 'Disable account and request deletion' }).disabled).toBe(false)
  expect(mocks.signOut).not.toHaveBeenCalled()
})
