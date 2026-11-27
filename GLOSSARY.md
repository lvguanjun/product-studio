# Product Studio

A local-first studio for turning raw product photos and mobile screenshots into clean, pure-white e-commerce main images in batches.

## Language

**Source Image**:
An uploaded raw product photo or screenshot queued for white-background generation.
_Avoid_: Input file, raw upload, original photo

**Product Image**:
A generated white-background output image produced from a **Source Image** and persisted on disk.
_Avoid_: Result, output file, artifact

**Batch**:
The current in-browser working set of **Source Images** and their generated **Product Images** in the batch workspace.
_Avoid_: Queue, list, job

**History**:
Previously generated **Product Images** persisted on disk across sessions, browsed outside the current **Batch**.
_Avoid_: Archive, logs

**Batch Export**:
Downloading multiple completed **Product Images** together in one action, as opposed to downloading a single image from its card or preview modal.
_Avoid_: Bulk save, mass download

**ZIP Export**:
A **Batch Export** mode that packages completed **Product Images** into a single ZIP archive.
_Avoid_: Archive download, bundle

**Folder Export**:
A **Batch Export** mode that writes completed **Product Images** directly as individual files into a user-chosen local folder without archiving.
_Avoid_: Multi-download, direct download, bulk save

**Export Filename**:
The human-readable filename presented to the user when saving a **Product Image**, derived from its **Source Image** name without internal random identifiers.
_Avoid_: Display name, clean filename
