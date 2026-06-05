from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "screenshots"

VIEW_FILES = [
    "index.html",
    "login_view.html",
    "dashboard_view.html",
    "students_view.html",
    "classes_view.html",
    "presence_camera_view.html",
    "attendance_view.html",
    "settings_view.html",
]


def main():
    OUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)

        for view_file in VIEW_FILES:
            source = BASE_DIR / view_file
            output = OUT_DIR / f"{source.stem}.png"
            page.goto(source.resolve().as_uri(), wait_until="networkidle")
            page.screenshot(path=str(output), full_page=True)
            print(output)

        browser.close()


if __name__ == "__main__":
    main()
