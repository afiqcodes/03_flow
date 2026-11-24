# flow

A compact personal workspace built with Flask and PostgreSQL. The interface pairs a content window with a dedicated form window and includes a home dashboard, tasks, notes, projects, a daily logbook, an expense tracker, monthly budgets, subscription billing, and categorized bookmarks.

See [LOGBOOK.md](LOGBOOK.md) for the development change log.

## Features

- **Home Dashboard** — use the home icon beside the calendar shortcut to see open tasks, tasks due today or earlier, upcoming subscription bills, active projects, recent logs, and pinned or recent notes. The side panel offers quick actions and the current month's recorded income, spending, and budget comparison. Tasks remain at `/`; the dashboard is at `/dashboard`.
- **Notes** — under Personal, create, edit, pin, search, and delete plain-text notes. Optionally link notes to projects or tasks. Pinned notes appear first, followed by the most recently edited notes. Removing a linked project or task preserves its notes.
- **Expense Tracker** — open `EXPENSEs` under Finance to record income and expenses, choose categories, browse months, and edit or delete transactions. Compare actual spending with the corresponding monthly budget. Amounts use the same dollar display as existing finance pages, with up to two decimal places. Subscription payments link back to their plan and count toward actual spending when paid.
- **Tasks** — choose a type (Work, Finance, Home, Personal, Health, Errands, or Others), then save a description, due date and time, priority, and difficulty. Tasks appear under their type with separate priority sections (Urgent to Low), ordered by difficulty (Hard to Easy) and then newest first within each section. Priority levels use divider lines, while difficulty remains a colored badge: red for Hard, yellow for Medium, and green for Easy. Expand a task to view its details, or add, edit, complete, and delete tasks in place.
- **Budgets** — plan income, savings, and expense categories for every month; compare yearly totals and automatically calculate the remaining balance.
- **Logbook** — write one diary entry per date, including weekends and past or future dates; browse saved years through 12 expandable month rows and open any day in a detail modal. Record a title, location, description, and day type (Work, Holiday, MeTIME, Family). Edit entries, attach images, and download the original files.
- **Subscription billing** — track monthly or yearly plans, upcoming charges, active status, and category. Choose **record payment**, confirm the payment date, and save to add a linked Bills expense and advance the next billing date. Open **payment history** to browse that plan's expenses by month.
- **Bookmarks** — save validated HTTP(S) links and organize them with the same categories used for subscriptions.
- **Projects** — save a title, description, status, optional GitHub and website links, a main image, and downloadable files. Browse three-column cards, open details in a modal, and edit the project or its attachments.
- **Calendar** — browse any year from the icon in the content window's top-right corner. Choose a Malaysian state or federal territory to show its published public holidays. Holiday results are cached in PostgreSQL and refreshed daily.
- **API** — explore eight service slots under Information. Each card opens a request and response workspace with metadata, example data, and HTTP status feedback. API a connects to the local dummy API; the other slots use sample responses until handlers are connected.
- **FILE FORMATs** — under Information, combine JPG/PNG images into a PDF, export PDF pages as PNG/JPG images in a ZIP, or convert DOCX/XLSX/PPTX/ODT files to PDF. Reorder images before combining them and choose a page range and resolution for PDF exports. Files are processed locally for the download and are not saved to PostgreSQL.
- **Navigation** — click the `flow` logo to slide the grouped side navigation open or closed. An open sidebar stays visible across page changes in the same tab. Click outside it, interact with the page, press Escape, or click the logo to close it. Motion follows the browser's reduced-motion preference.
- **Appearance** — use the palette button in the webpage's lower-right corner to choose a background color, and the floating sun and moon switch in the upper-right corner to choose light or dark mode. Both choices are stored in the browser. Each mode generates a matching palette from the chosen color. On the Tasks page, category headings use a gradient based on the chosen color, category icon strokes use that exact color on a contrasting tile, and priority divider lines follow the theme accent. Without a saved color, task types retain their distinct default icon colors.
- **Persistent data** — PostgreSQL data is retained in the `todo_data` Docker volume.

## Tech stack

- Python 3.12 and Flask
- PostgreSQL 17
- Jinja templates
- Vanilla JavaScript and CSS
- Docker Compose

## Run with Docker

### Prerequisites

- Docker Engine or Docker Desktop
- Docker Compose v2

### 1. Configure the database

Create or update the existing `.env` file in the project root:

```env
POSTGRES_DB=todo
POSTGRES_USER=todo_user
POSTGRES_PASSWORD=replace_with_a_strong_password
```

The `.env` file is ignored by Git. The Compose configuration passes these values to both the Flask and PostgreSQL containers.

### 2. Start the application

```bash
docker compose up --build
```

Open [http://localhost:5000](http://localhost:5000). The web container waits for PostgreSQL to become healthy, then creates or upgrades the required tables automatically.

To run in the background:

```bash
docker compose up --build -d
```

View logs with:

```bash
docker compose logs -f web
```

### 3. Stop the application

```bash
docker compose down
```

This preserves the database volume. To also delete all saved application data, run `docker compose down -v`.

## Project structure

```text
.
├── app.py                 # Flask routes, validation, and database setup
├── api_services.py        # Editable API definitions and integration hooks
├── file_conversions.py    # Image, PDF, and Office conversion helpers
├── uploads.py             # Shared image validation and stored-file responses
├── LOGBOOK.md             # Development change log
├── compose.yaml           # Web and PostgreSQL services
├── Dockerfile             # Flask application image
├── requirements.txt       # Python dependencies
├── schema.sql             # PostgreSQL tables and compatibility upgrades
├── static/
│   ├── css/
│   │   ├── base.css          # App layout, navigation, and shared forms
│   │   ├── components.css    # Shared cards, calendars, icons, and dialogs
│   │   ├── workspace.css     # Dashboard, Notes, and Expense Tracker
│   │   ├── tasks.css
│   │   ├── budgets.css
│   │   ├── subscriptions.css
│   │   ├── bookmarks.css
│   │   ├── projects.css
│   │   ├── calendar.css
│   │   ├── logbook.css
│   │   ├── api.css
│   │   └── file_formats.css
│   └── js/
│       ├── app.js            # Navigation, shared dialogs, in-place updates
│       ├── theme.js          # Background picker and adaptive interface colors
│       ├── tasks.js          # Task details
│       ├── budgets.js        # Year statistics and budget calculator
│       ├── expenses.js       # Transaction category controls
│       ├── logbook.js        # Day dialog, year picker, image previews
│       ├── api.js            # API request/response display
│       └── file_formats.js   # Conversion downloads and image page order
└── templates/
    ├── base.html          # Shared two-window layout and navigation
    ├── workspace.html     # Shared styles for Dashboard, Notes, and Expense Tracker
    ├── dashboard.html     # Daily overview and quick actions
    ├── notes.html         # Searchable notes and editor
    ├── expenses.html      # Transactions and monthly budget comparisons
    ├── index.html         # Tasks
    ├── budgets.html       # Monthly and yearly budgets
    ├── logbook.html       # Daily logs, year/month browsing, and image forms
    ├── upload_error.html  # Oversized upload feedback
    ├── subscriptions.html # Subscription billing
    ├── bookmarks.html     # Categorized bookmarks
    ├── projects.html      # Project cards, details, and form
    ├── calendar.html      # Year calendar and Malaysian public holidays
    ├── api.html           # API service cards and request dialogs
    ├── file_formats.html  # File conversion tools and upload form
    └── macros.html        # Reusable category icons and options
```

## Frontend organization

`base.html` loads `css/base.css`, `css/components.css`, `js/theme.js`, and `js/app.js` on every page. Both scripts run in the head so the saved theme and per-tab sidebar state apply before the page is shown; controls initialize when the DOM is ready. The sun and moon icons are PNGs in `static/images/`, and the switch track uses a lighter or darker shade of the selected background color to match the active mode. Each section adds its own stylesheet through the `page_styles` template block and its script, when needed, through `page_scripts`. Dashboard, Notes, and Expense Tracker extend `workspace.html` to share `workspace.css`. Bookmarks and Subscriptions use the shared scripts only.

The shared script submits non-Task forms in the background, refreshes the affected page content, and reinitializes that page's controls. Same-page edit links, year selectors, and Calendar settings update in place. Tasks use their own script for card-level animations. Ordinary Flask forms and redirects remain available when JavaScript is disabled. The background picker and theme switching require JavaScript; browser storage preserves their choices across visits.

Keep each section's styles and responsive rules in its matching CSS file. Put reusable components in `components.css` and app-wide layout or form changes in `base.css`. Shared calendar classes are used by Budget and Logbook; category icons are shared by Bookmarks and Subscriptions. A section should not need to load another section's stylesheet.

`h1` and `h2` headings use Jost from Google Fonts, with a sans-serif fallback. Body text uses a system monospace stack. The locally bundled Sulphur Point and Press Start 2P fonts remain in `static/fonts/` but are not currently used by the stylesheets.

## Application routes

| Page | URL |
| --- | --- |
| Tasks | `/` |
| Home Dashboard | `/dashboard` |
| Notes | `/notes` |
| Expense Tracker | `/expenses` |
| Budgets | `/budgets` |
| Logbook | `/logbook` |
| Subscription Billing | `/subscriptions` |
| Bookmarks | `/bookmarks` |
| Projects | `/projects` |
| Calendar | `/calendar` |
| API | `/api` |
| FILE FORMATs | `/file-formats` |

Create, toggle, and delete operations use POST routes from the forms in each page.

## Connect your own APIs

Edit a service in `api_services.py` to change its name, description, version, auth label, expected latency label, request `fields`, and `example_response`. The template builds the card and modal from that definition. Each field needs a unique `name`, a `label`, a `type` (`text`, `month`, or `select`), and an `example`; select fields also need `options`. The example values are prefilled in the request form.

Requests from the modal use POST to `/api/services/<slug>/request`; the method shown on each card describes this local request. API a forwards `user_id` to the `dummy-api` Compose service at `/v1/spending/lookup` and displays its response and status. The other slots return their example response for the example field values, `404` for an unknown sample record, and `400` for missing or invalid fields. To connect another service, add a function in `api_services.py` that accepts the validated field values and returns `(JSON-serializable response, HTTP status)`, then register it in `SERVICE_HANDLERS`. The handler can use whichever method the external API requires:

```python
def call_my_service(values):
    # Use values["city"] to request your real service here.
    return {"data": {"city": values["city"]}}, 200

SERVICE_HANDLERS["api-b"] = call_my_service
```

Keep API keys in environment variables and make external requests from the server handler. The browser only receives the response returned by the handler. Replace the sample metadata and example response when connecting each service.

## Data model notes

- Notes store a title and plain-text content, a pinned flag, timestamps, and optional project and task references. Content is escaped when rendered, and links use `ON DELETE SET NULL`.
- Transactions store a positive decimal amount, type (income or expense), category, date, title, and optional details. Expense categories match budget categories (food, transport, bills, entertainment), plus Others; income categories are Salary, Freelance, Refunds, and Others. Others expenses count toward total spending but have no allocated category budget. Monthly net cash flow is recorded income minus recorded expenses, and expense budget left is planned expenses minus actual expenses.
- Dashboard and transaction dates use Asia/Kuala_Lumpur. New tables are added through the same idempotent startup schema as existing modules.
- Budget remaining is calculated as `income - savings - food - transport - bills - entertainment`.
- Yearly subscription prices are divided by 12 when estimating monthly spend.
- Recording a subscription payment saves its full price as a Bills expense on the selected payment date, including the full yearly price for yearly plans. It advances the schedule one cycle from the bill's due date. For overdue plans, record each paid bill separately. Upcoming or paused subscriptions do not automatically add expenses; free plans do not need payment entries.
- Payment creation and schedule advancement share a transaction. A locked subscription row, submitted due date, and unique subscription/bill index prevent duplicate bill recording. Month-end billing days are preserved across shorter months, and yearly February 29 bills return to February 29 in leap years.
- Subscription payment history filters transactions by plan and month; the overview and budget totals still cover all transactions that month. Existing expenses are not automatically matched to subscriptions.
- Editing a linked payment can adjust the amount, date, category, or details, but it remains an expense. Editing or deleting the expense does not rewind the subscription schedule. Deleting a subscription preserves recorded expenses, their original titles, and bill dates, while clearing the reference to the deleted plan.
- Bookmark URLs accept only HTTP and HTTPS. A missing scheme is normalized to HTTPS on the server.
- Subscription and bookmark categories are Gaming, Telecommunications, Streaming, Software, Finance, Productivity, Education, Fitness, Work, and Others.
- Tasks saved before task types were added, and existing Study tasks, appear under Others.
- Each Logbook date has one entry. To add more details to an existing day, open it and choose **Edit log**. A duplicate date is rejected without replacing the original entry.
- Logbook accepts up to 10 JPEG, PNG, GIF, or WebP images per entry, each at most 5 MB and 20 megapixels. Image contents are validated with Pillow; original bytes are stored in PostgreSQL alongside the log, so the existing `todo_data` volume retains them across restarts and rebuilds. Include this volume in backups; images increase its size.
- Editing preserves attached images unless **Remove on save** is checked. Entry changes, image removal, and new uploads commit together. Download links return the original uploaded image bytes with a sanitized filename.
- The Logbook year selector includes the current year and all years with saved entries. Saving an entry for another year makes that year available automatically.
- Projects use Ongoing, In Review, or Completed when created; editing also offers Terminated. Status colors are yellow, blue, green, and red respectively.
- Calendar holidays come from the [Malaysia Holiday API](https://malaysia-holiday.dydxsoft.my/api/docs), which does not require an API key. Its published holiday data covers 2000–2100; the calendar grid works for years 1–9999. The selected state's results are cached for one day. If the API is unavailable, saved results remain visible.
- Project files accept any file type, up to 10 files per project and 20 MB each. The main image accepts JPEG, PNG, GIF, or WebP, up to 5 MB and 20 megapixels. The complete upload request is limited to 55 MB. Files and images are stored in PostgreSQL and retained by the `todo_data` volume. Files download as attachments.

## Local development without Docker

Run PostgreSQL separately, then provide the connection settings expected by `app.py`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DB_HOST=localhost
export DB_NAME=todo
export DB_USER=todo_user
export DB_PASSWORD=your_password

python app.py
```

FILE FORMATs requires the `PyMuPDF` package from `requirements.txt`. Office conversion also requires LibreOffice Writer, Calc, and Impress plus fonts installed on the machine. The Dockerfile includes these packages; rebuild the web image after adding this feature:

```bash
docker compose up -d --build web
```

The converter accepts up to 20 JPG/PNG images, each at most 5 MB and 20 megapixels, with a combined limit of 40 megapixels. Transparent areas become white in the PDF, and EXIF orientation is applied. Image page order can be adjusted using the arrow buttons.

PDF and Office uploads are limited to 20 MB each. PDF export supports PNG/JPG at 72, 150, 200, or 300 DPI, up to 50 pages per conversion, with limits on rendered pixel count. Export fewer pages or reduce DPI for large documents. The complete upload is limited to 55 MB and the converted download to 50 MB. Password-protected files must be unlocked before uploading.

Office conversion uses a separate temporary LibreOffice profile for each request and stops conversions after 60 seconds. Intermediate files are removed when conversion finishes or fails. Document layout can differ when fonts or Office-specific features differ. Conversion does not call external services or store files in the database.

The app listens on `0.0.0.0:5000`. This project currently uses Flask's built-in server and has no authentication, so it is intended for local development and learning rather than public deployment.

## Quick checks

```bash
python -m py_compile app.py api_services.py uploads.py file_conversions.py
python -m unittest discover -s tests -v
node --test tests/test_navigation.js
for file in static/js/*.js; do node --check "$file"; done
docker compose config
```

The Python suite skips PostgreSQL integration checks unless the variables below are set. Real Office conversion checks require LibreOffice (included in Docker). Logbook, Projects, and Workspace integration checks use a separate test database and create/remove their own schemas:

```bash
LOGBOOK_TEST_DATABASE_URL=postgresql://user:password@localhost/test_database \
PROJECT_TEST_DATABASE_URL=postgresql://user:password@localhost/test_database \
WORKSPACE_TEST_DATABASE_URL=postgresql://user:password@localhost/test_database \
  python -m unittest discover -s tests -v
```
