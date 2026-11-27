Status: accepted

# Prioritize Folder Export as Default over HTTPS

When the browser runs in a secure context and exposes the File System Access API (`showDirectoryPicker`), we make **Folder Export** the primary **Batch Export** action in the **Batch** workspace and move **ZIP Export** into the split-button dropdown menu. Browsers without `showDirectoryPicker` (Safari, Firefox, mobile browsers, and plain HTTP deployments) hide the split dropdown and fall back cleanly to **ZIP Export** as the sole batch action. This supersedes ADR-0002's choice of defaulting to **ZIP Export** everywhere, while keeping ADR-0002's decisions on no throttled multi-anchor downloads, clean **Export Filenames**, single-image direct download, and **History** scope.

## Considered Options

- **Keep ZIP Export as default (ADR-0002)**: uniform button behavior across browsers, but adds a repeated unzip-and-cleanup step to the core desktop e-commerce workflow of uploading 3–15 **Product Images** directly to seller backends.
- **Sticky user preference (`localStorage`)**: remembers whichever mode was clicked last, but silently mutates the primary toolbar button after an occasional **ZIP Export** and breaks predictable UI muscle memory.
- **Side-by-side export buttons**: exposes both **Folder Export** and **ZIP Export** without a dropdown, but crowds the 4-action **Batch** toolbar alongside generation, retry, and clear actions.

## Consequences

- **Explicit safeguard without extra modal**: `showDirectoryPicker` already acts as a system-level confirmation and permission gate; showing the ready **Product Image** count on the primary button (`>= 2` items) makes write scale obvious without adding an extra confirmation dialog.
- **Stable disabled and single-image states**: at 0 completed **Product Images**, the disabled primary button reflects the environment's default mode (`保存到文件夹` when supported, `打包下载 ZIP` otherwise) to avoid label jumping; at 1 completed **Product Image**, it directly downloads that single file without opening a directory picker or split menu.
- **Lightweight failure fallback**: when **Folder Export** fails on restricted directories or denied permissions, a concise toast directs the user to the split dropdown's **ZIP Export** rather than auto-triggering a ZIP download or introducing stateful toast actions.
- **Unchanged History boundary**: **History** remains **ZIP Export** only until explicit multi-item selection is added.
