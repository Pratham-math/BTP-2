import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { ThemeProvider, ThemeToggle } from './theme'

let listeners, media
beforeEach(() => {
  localStorage.clear(); delete document.documentElement.dataset.theme
  listeners = new Set()
  media = { matches: false, addEventListener: vi.fn((_, listener) => listeners.add(listener)), removeEventListener: vi.fn((_, listener) => listeners.delete(listener)) }
  vi.stubGlobal('matchMedia', vi.fn(() => media))
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); delete document.documentElement.dataset.theme })
const show = () => render(<ThemeProvider><ThemeToggle /></ThemeProvider>)

it('switches modes, saves the choice and restores it after remount', () => {
  const view = show()
  fireEvent.click(screen.getByRole('button', { name: 'Switch to dark mode' }))
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(localStorage.getItem('btp2.theme')).toBe('dark')
  expect(screen.getByRole('button', { name: 'Switch to light mode' }).getAttribute('aria-pressed')).toBe('true')
  view.unmount(); show()
  expect(document.documentElement.dataset.theme).toBe('dark')
  fireEvent.click(screen.getByRole('button', { name: 'Switch to light mode' }))
  expect(document.documentElement.dataset.theme).toBe('light')
})

it('follows system changes until a manual preference is saved', () => {
  media.matches = true
  show()
  expect(document.documentElement.dataset.theme).toBe('dark')
  act(() => listeners.forEach(listener => listener({ matches: false })))
  expect(document.documentElement.dataset.theme).toBe('light')
  fireEvent.click(screen.getByRole('button', { name: 'Switch to dark mode' }))
  act(() => listeners.forEach(listener => listener({ matches: false })))
  expect(document.documentElement.dataset.theme).toBe('dark')
})

it('switches even if browser storage is unavailable', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Blocked storage') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Blocked storage') })
  show()
  fireEvent.click(screen.getByRole('button', { name: 'Switch to dark mode' }))
  expect(document.documentElement.dataset.theme).toBe('dark')
})

it('synchronizes theme changes across tabs', () => {
  show()
  act(() => window.dispatchEvent(new StorageEvent('storage', { key: 'btp2.theme', newValue: 'dark' })))
  expect(document.documentElement.dataset.theme).toBe('dark')
  act(() => window.dispatchEvent(new StorageEvent('storage', { key: 'btp2.theme', newValue: null })))
  expect(document.documentElement.dataset.theme).toBe('light')
})

it('applies the saved theme before React starts', () => {
  localStorage.setItem('btp2.theme', 'dark')
  const script = readFileSync(resolve('public/assets/theme-init.js'), 'utf8')
  new Function(script)()
  expect(document.documentElement.dataset.theme).toBe('dark')
  localStorage.setItem('btp2.theme', 'invalid-preference')
  media.matches = true
  new Function(script)()
  expect(document.documentElement.dataset.theme).toBe('dark')
})
