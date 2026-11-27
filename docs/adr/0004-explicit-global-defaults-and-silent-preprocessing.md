Status: accepted

# Explicit Server Global Defaults and Silent Input Preprocessing

We move the five advanced generation and export settings (model, quality, concurrency, export size, and export format) out of browser `localStorage` into server-persisted **Global Defaults** stored under `OUTPUT_DIR`, updated only when the user explicitly saves them from the Advanced Settings drawer. Unsaved edits remain scoped to the current page session so temporary experiments never silently overwrite defaults or diverge across browsers. At the same time, we remove all user-facing input optimization toggles (along with long-screenshot cropping and small-image sharpening) and keep a single silent backend preprocessing pipeline for every **Source Image**: EXIF orientation normalization, transparent-to-white RGB flattening, high-resolution downscaling capped at a `2048px` max edge, and JPEG (quality 95) encoding for gateway upload.

## Considered Options

- **Auto-overwrite server Global Defaults on every change**: zero extra click when intentionally changing defaults, but turns any one-off test (such as temporarily trying `high` quality or a different model) into a silent mutation affecting all browsers and future sessions.
- **Keep browser `localStorage` overrides alongside server defaults**: preserves unsaved tweaks across refreshes, but causes stale per-browser caches to shadow updated **Global Defaults** on other devices.
- **Keep a user toggle for high-resolution compression (or drop compression altogether)**: lets users send full 12MP–48MP originals, but adds UI complexity for little gain when target **Product Images** are `1024×1024` and image-edit models already cap high-detail input around `2048px`.
- **Keep PNG encoding for `2048px` preprocessed uploads**: avoids lossy re-encoding, but inflates real-world photos to 4–8 MB per request and slows concurrent uploads after alpha transparency has already been flattened to white RGB.

## Consequences

- **Three-tier settings clarity**: the Advanced Settings drawer distinguishes factory defaults (code), server **Global Defaults** (persisted under `OUTPUT_DIR`), and current-page temporary edits; resetting to factory defaults only resets the form until explicitly saved as **Global Defaults**, and the header dirty indicator signals unsaved session overrides.
- **Zero deployment changes**: **Global Defaults** live inside the existing `OUTPUT_DIR` volume without new environment variables; personal UI preferences (custom prompt templates, inspect backdrop, and 80% safe frame) remain in browser `localStorage`.
- **Cleaner API and UI**: `/api/generate` drops preprocessing toggle form fields, and **Product Image** cards and compare modals drop preprocess badges and screenshot-crop notices.
