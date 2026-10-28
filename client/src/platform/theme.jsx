import { createContext, useContext, useEffect, useLayoutEffect, useState } from 'react'

const ThemeContext = createContext(null)
const validTheme = value => value === 'dark' || value === 'light' ? value : null
function savedTheme() { try { return validTheme(localStorage.getItem('btp2.theme')) } catch { return null } }

export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(savedTheme)
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? document.documentElement.dataset.theme === 'dark')
  const theme = preference || (systemDark ? 'dark' : 'light')
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#101814' : '#f7f8f4')
  }, [theme])
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    const updateSystem = event => setSystemDark(event.matches)
    const updateSaved = event => { if (event.key === 'btp2.theme' || event.key === null) setPreference(event.key === null ? null : validTheme(event.newValue)) }
    media?.addEventListener('change', updateSystem)
    window.addEventListener('storage', updateSaved)
    return () => { media?.removeEventListener('change', updateSystem); window.removeEventListener('storage', updateSaved) }
  }, [])
  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark'
    setPreference(next)
    try { localStorage.setItem('btp2.theme', next) } catch { /* The current tab still switches when storage is unavailable. */ }
  }
  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>
}

export const useTheme = () => useContext(ThemeContext)

export function ThemeToggle({ className = '' }) {
  const { theme, toggleTheme } = useTheme()
  return <button type="button" className={`secondary theme-toggle ${className}`} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} aria-pressed={theme === 'dark'} onClick={toggleTheme}>
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">{theme === 'dark' ? <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5" /></> : <path d="M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z" />}</svg>
    <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
  </button>
}
