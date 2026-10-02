# Academy interface standard

Applies to the public website, classroom, written guides, video controls, instructor views and Academy-owned support controls.

## Controls

- Use a clear verb and object: **Read guide**, **Watch video**, **Start learning**, **Close the library**.
- Navigation and call-to-action buttons are text-led. Do not append decorative arrows.
- Use `/ui-icons.svg` for familiar actions only: play, pause, close, expand, collapse, reading, calendar and messages.
- Do not use emoji, Unicode arrow characters or font glyphs as UI icons. Do not try to fix their appearance with an emoji variation selector or font fallback.
- Reuse `.academy-icon` from `/ui-controls.css`. Its default size is 18px. Icons inherit the control colour and are hidden from assistive technology when the control already has a name.
- Give every icon-only button an explicit accessible label and a minimum 44px touch target.
- The Academy brand uses the vector `brand` symbol. Keep it separate from CTA iconography.
- Preserve focus rings, visible hover/pressed states, keyboard operation, disclosure state and reduced-motion support.
- Mathematical signs, market direction and status values inside product data are semantic content, not decorative control icons.

## Adding or updating a section

1. Reuse the existing text-button, primary, secondary and disclosure patterns.
2. Review the final rendered state, including dialogs and controls produced by JavaScript.
3. Check at narrow mobile width and desktop. Avoid overflow, hidden labels and undersized touch targets.
4. Confirm the label matches the actual action. Written-guide cards must not imply immediate video playback.
5. Verify keyboard names, menu/disclosure state and close behaviour.
6. Update the shared release revision for entrypoints and imported modules. Rebuild matching gzip files. A cached older renderer must not restore deprecated controls.

The shared symbol library is the source of truth; add a new symbol there rather than inventing a local icon style.
