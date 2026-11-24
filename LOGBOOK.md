# Development logbook

This file records changes to the application. Add new entries under the date they are made, with the newest entry first.

## 2026-11-05

### File format icons

- Added theme-aware SVG conversion icons above each File Formats card heading for Images to PDF, PDF to images, and Office to PDF.
- Centered the icons and headings, removed the icon tiles and top-right format badges, and simplified the card footers to a divider without labels.

### Navigation transitions

- Fixed the theme transition overriding the sidebar slide animation and added matching open/close and backdrop transitions.
- Restore the sidebar's per-tab open state before painting each page, keeping it steady during supported browser page transitions.
- Close navigation on page clicks, keyboard focus, scrolling gestures, Escape, or the logo. Closed navigation is inert, and reduced-motion preferences disable its animations.
- Added navigation regressions for page changes, dismissal, focus, browser back/forward restoration, and unavailable storage.

## 2026-11-03

### Dashboard, Notes, and Expense Tracker

- Added a Home Dashboard shortcut beside the calendar icon, with due tasks, upcoming bills, recent logs and notes, monthly finances, and quick actions.
- Added Notes under Personal, including search, pinning, editing, deletion, and optional links to projects and tasks.
- Added Expense Tracker under Planning, with income and expense transactions, monthly totals, and comparisons against existing budget categories.
- Moved Expense Tracker into Finance and renamed its navigation label to `EXPENSEs`.
- Added PostgreSQL tables through the startup schema, shared theme-aware page styles, and route and database regression checks. Made the expanded navigation scrollable on smaller screens.

### Maintenance

- Moved shared image validation and stored-file responses into `uploads.py`.
- Added one transaction context for database operations so connections close after success or rollback, with regression checks for connection cleanup.
- Consolidated API and Project dialog controls in the shared script, including dialogs replaced during page updates, and removed the redundant Project script.
- Simplified API handler registration and updated the project structure documentation.

## 2026-10-21

### Appearance

- Connected the background color picker to the interface palette. The selected color is stored in the browser and produces matching light or dark surfaces, borders, text, and accent colors across pages.
- Added a gradient to each Task category heading using the selected background color.
- Made Task category icon strokes use the exact selected background color. Their tile color adjusts to keep the icons readable. When no color has been selected, the seven task types keep their distinct default icon colors.

### Tasks

- Grouped tasks by type, then by priority from Urgent to Low. Within a priority group, tasks are ordered by difficulty from Hard to Easy, then newest first.
- Replaced priority badges with labeled sections and divider lines. The lines use progressively stronger theme accent color for higher priorities.
- Kept difficulty as a badge, using darker green for Easy, yellow for Medium, and red for Hard.

### Maintenance

- Bounded the Task icon contrast adjustment loop to a fixed number of steps.
- Removed unused font imports and declarations from the shared stylesheet.
- Updated `README.md` to describe the current Task layout, adaptive appearance, and fonts.
