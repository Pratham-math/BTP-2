import { act, cleanup, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ScenePlayer } from './ScenePlayer'

const mounts = vi.hoisted(() => ({ count: 0, props: [] }))
vi.mock('@remotion/player', async () => {
  const { forwardRef, useEffect, useImperativeHandle } = await import('react')
  return { Player: forwardRef((props, ref) => {
    useEffect(() => { mounts.count += 1 }, [])
    useImperativeHandle(ref, () => ({ seekTo: vi.fn(), getCurrentFrame: () => 0, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
    mounts.props.push(props.inputProps)
    return <div>player</div>
  }) }
})
afterEach(cleanup)

it('keeps playing when the session re-sends the same scene and re-signs its URLs', async () => {
  const scene = () => ({ id: 's1', utterances: [{ text: 'One line of narration.', visual_step: 0 }], visual: { kind: 'bullets', items: ['a'] } })
  const view = render(<ScenePlayer scene={scene()} audioUrl="/a?sig=1" duration={4} index={0} total={1} />)
  await act(async () => {})
  // A progress save returns a new session object and a later refresh re-signs the audio URL.
  view.rerender(<ScenePlayer scene={scene()} audioUrl="/a?sig=2" duration={4} index={0} total={1} />)
  await act(async () => {})
  expect(mounts.count).toBe(1)
  expect(mounts.props.at(-1).audio).toBe('/a?sig=1')
})
