import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { AdaptiveStatus } from './AdaptiveStatus'

afterEach(cleanup)
it('distinguishes a provisional learning signal from the actual current video', () => {
  render(<AdaptiveStatus objectiveId="o1" adaptivity={{ mode: 'rolling', lead_blocks: 3, understanding: {
    level: 'supportive', score: 25, observed_objectives: 1, reason: 'More scaffolding would help.' },
    current_teaching: null, planned: [{ objective_id: 'o3', number: 4, level: 'supportive', based_on_assessment: 1 }] }} />)
  expect(screen.getByText(/25\/100 from 1 assessed concept/)).toBeTruthy()
  expect(screen.getByText(/not a grade or an ability diagnosis/)).toBeTruthy()
  expect(screen.getByText(/Normal difficulty/)).toBeTruthy()
  expect(screen.getByText(/Block 4: More support/)).toBeTruthy()
})
it('classrooms describe only reviewed routes', () => {
  render(<AdaptiveStatus adaptivity={{ mode: 'reviewed_classroom' }} />)
  expect(screen.getByText(/does not generate unreviewed videos/)).toBeTruthy()
  expect(screen.queryByText(/Learning signal/)).toBeNull()
})
