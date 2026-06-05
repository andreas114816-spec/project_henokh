# Final Product Page Views

Open `index.html` in a browser to choose a separate realistic static preview for each view.

The preview is based on the current Flask/Jinja templates and mirrors the final product screens without requiring a running server or database.

- `login_view.html`
- `dashboard_view.html`
- `students_view.html`
- `classes_view.html`
- `presence_camera_view.html`
- `attendance_view.html`
- `settings_view.html`
- `final_product_preview.html` keeps the combined preview.

Real browser screenshots of the HTML pages are generated in `screenshots/`:

- `screenshots/index.png`
- `screenshots/login_view.png`
- `screenshots/dashboard_view.png`
- `screenshots/students_view.png`
- `screenshots/classes_view.png`
- `screenshots/presence_camera_view.png`
- `screenshots/attendance_view.png`
- `screenshots/settings_view.png`

Run `../../.venv/bin/python screenshot_html_views.py` from this folder to regenerate the real screenshots.

The `png/` folder contains older programmatic mockup renders:

- `png/index.png`
- `png/login_view.png`
- `png/dashboard_view.png`
- `png/students_view.png`
- `png/classes_view.png`
- `png/presence_camera_view.png`
- `png/attendance_view.png`
- `png/settings_view.png`

Run `python3 render_png_previews.py` from this folder to regenerate the PNG files.
