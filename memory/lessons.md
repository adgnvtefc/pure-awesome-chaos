# Lessons

Distilled from past nights. Injected into every session's system prompt.
Edit freely: add your own, delete bad ones.

- (2026-10-06) Build the pure logic and tests first, then wrap it in the TUI, so UI bugs are easy to isolate and the core stays trustworthy.
- (2026-10-06) Add a headless demo/subprocess test early because it catches CLI, TUI, screenshot, and exit-code problems that unit tests miss.
- (2026-10-06) Encode spec-critical invariants as tests immediately — exact counts, deterministic behavior, crisis bypass, and UI-visible labels — to avoid late rewrites.
- (human) Textual's App.save_screenshot() writes SVG, not PNG: give it a .svg filename. For a real PNG, draw it with Pillow.
