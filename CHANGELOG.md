# Changelog

## 0.1.2 (Unreleased)

- Pause on ambiguous columns, show bounded examples and resume with an explicit choice.
- Preserve already saved files; support cancellation and source-change checks during selection.
- Use the general CSV Total Time preference from battread 0.1.2.

## 0.1.1

- Use battread 0.1.1 to process Neware CSV exports without a named `Step Type`,
  including streaming and ordered merge.
- Avoid OpenBLAS thread-buffer allocation spikes when starting portable workers.

## 0.1.0

- Convert individual files or merge them in a chosen order with local processing.
- Responsive progress, cancellation, memory containment and temporary-file cleanup.
- Editable names, automatic conflict numbering and source-specific diagnostics.
- Current bounded MPR reader and explicit Ewe/V selection through battread.
- Windows portable package with startup feedback, original grayscale icon and
  bundled license/source information.
- Added a single-file Windows download with a grayscale extraction-time splash.
- The portable launcher cleans extracted libraries on normal exit; the folder
  build remains a local development intermediate.
- Release preparation uses temporary source staging instead of a second checkout.
