# Project working instructions

Build the small prompt-to-video MVP only. The current scope is one text prompt,
Gemini-written visual plans and narration, Gemini speech, local Manim animations,
Pillow slides for older saved jobs, FFmpeg rendering, and one playable/downloadable MP4. Do not add quizzes, accounts,
uploads, a database, or a worker framework yet.

Keep the React interface and FastAPI implementation small and explainable.
Never put the Gemini key in frontend code or logs. A synthetic test tone may
verify rendering in offline tests, but it is not evidence of live narration.

Core checks are `.venv\Scripts\python -m pytest -q` and `npm run build` from
the `client` directory.
