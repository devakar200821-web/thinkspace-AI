# ThinkSpace AI

Static web app (no build step). Plain HTML/CSS/JS.

## Run in VS Code
1. Open the `thinkspace-ai` folder in VS Code (File → Open Folder).
2. Install the **Live Server** extension.
3. Right-click `index.html` → **Open with Live Server**.

## Structure
- `index.html` – sign-in/sign-up + dashboard layout
- `css/styles.css` – the original dark navy/cyan UI
- `js/auth.js` – sign up / sign in (browser-only prototype)
- `js/app.js` – upload, paste text, generation, projects, history, templates, settings

## What works
- Sign up / sign in (stored in localStorage, passwords hashed – NOT production security)
- Upload TXT/MD/CSV, drag & drop, paste text
- Summary, Mind Map (SVG), Report, Presentation (slide viewer) generated locally
- Save projects, history, templates, settings

## Next steps
- PDF/DOCX/image text extraction (needs a backend or pdf.js/mammoth)
- Replace `analyze()` / `build()` in `js/app.js` with a real AI API call via your own server (never put API keys in front-end code)
- Replace `js/auth.js` with a real auth provider (Firebase, Supabase, Auth0…)
