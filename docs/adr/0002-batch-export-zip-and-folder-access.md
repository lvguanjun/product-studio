# Default to ZIP Export with File System Access Folder Export over HTTPS

We keep **ZIP Export** as the default **Batch Export** action and offer **Folder Export** via the browser File System Access API (`showDirectoryPicker`) as a secondary split-button option in the **Batch** workspace, assuming the studio is served over HTTPS. Browsers that do not support `showDirectoryPicker` (such as Safari, Firefox, and mobile browsers) hide the Folder Export option and degrade cleanly to **ZIP Export**; we deliberately do not implement throttled multi-anchor (`<a>`) download loops.

## Considered Options

- **Throttled multi-anchor (`<a>`) downloads**: works over plain HTTP and across more desktop browsers without a folder picker, but triggers browser multi-download permission prompts, cannot reliably detect blocked or dropped files, offers no real write progress, and clutters the system Downloads folder on larger batches.
- **Folder Export as default (or sticky preference)**: saves one click for repeat desktop uploads, but risks accidental bulk writes on large batches and breaks muscle memory across browsers where only **ZIP Export** is available.
- **ZIP-only export**: simplest and universally reliable, but forces a manual unzip step on every high-frequency 3–15 image upload to e-commerce backends.

## Consequences

- **HTTPS requirement**: Folder Export relies on a secure context (`https://` or `localhost`); non-HTTPS LAN deployments will naturally fall back to ZIP-only without broken UI.
- **Clean Export Filenames**: both **ZIP Export**, **Folder Export**, and single-image downloads strip the internal random hex ID prefix to use `{source_stem}_white.{ext}` (auto-suffixing `_2`, `_3` on collisions, including existing files in a chosen folder), while server disk storage retains the unique ID prefix.
- **Scope boundary**: **Folder Export** applies only to completed **Product Images** in the active **Batch** (when at least 2 are completed; 1 completed image downloads directly as a single file). **History** remains **ZIP Export** only until explicit selection is introduced.
