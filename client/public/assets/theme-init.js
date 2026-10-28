// Apply the saved/system theme before the first paint, including while React loads.
(() => {
  let saved
  try { saved = localStorage.getItem('btp2.theme') } catch {}
  const dark = saved === 'dark' || (saved !== 'light' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#101814' : '#f7f8f4')
})()
