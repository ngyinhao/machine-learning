import argparse
import re
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread, Timer

from playwright.sync_api import expect, sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def check_browser(url, channel):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel)
        try:
            page = browser.new_page(reduced_motion="reduce")
            page.set_default_timeout(5000)
            errors = []

            def record_response(response):
                required_resources = {"document", "script", "stylesheet", "fetch", "xhr"}
                if response.status >= 400 and response.request.resource_type in required_resources:
                    errors.append(f"HTTP {response.status} from {response.url}")

            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("response", record_response)
            try:
                page.goto(url)
                expect(page.locator("#status")).to_have_text("Ready", timeout=25000)
                scrubber = page.get_by_role("slider", name="Trace tick")
                scrubber.press("End")
                expect(page.locator("#event")).to_contain_text("Returned to base")
                expect(page.locator("#map")).to_have_attribute("aria-label", re.compile(r"Parcel at the dock"))
                expect(page.locator("#reward-terms [data-term='Delivery']")).to_have_text("+100")
                page.locator("#episodes").fill("25")
                page.locator("#start").click()
                expect(page.locator("#status")).to_have_text("Complete")
                expect(page.locator("#progress")).to_have_attribute("value", "25")
                expect(page.locator("#chart-figure")).to_be_visible()
                expect(page.locator("#monitor-range")).to_have_text("Viewing episodes 1–25")
                expect(page.locator(".monitor-card strong")).to_have_text(["Episode 10", "Episode 20", "Episode 25"])
                expect(page.locator("#monitor-progress")).to_have_attribute("value", "1")
                selected = page.get_by_role("button", name=re.compile(r"^Inspect Episode 10,"))
                selected.click()
                expect(selected).to_have_attribute("aria-pressed", "true")
                expect(page.locator("#trace-title")).to_contain_text("Training episode 10")
                page.locator("#replay").click()
                expect(page.locator("#policy-evaluation")).to_be_visible()
                expect(selected).to_have_attribute("aria-pressed", "false")
                page.locator("#reference").click()
                expect(page.locator("#trace-title")).to_contain_text("Fastest collision-free route")
                expect(page.locator("#map-key-reference")).to_be_visible()
                expect(page.locator("#error")).to_be_hidden()
            finally:
                if errors:
                    raise RuntimeError("\n".join(errors))
        finally:
            browser.close()


def check_local(channel):
    with subprocess.Popen(
        [sys.executable, "-B", "app.py", "--port", "0"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        text=True,
    ) as server:
        try:
            startup_timeout = Timer(10, server.kill)
            startup_timeout.start()
            try:
                startup = server.stdout.readline().strip()
            finally:
                startup_timeout.cancel()
            url = startup.rpartition(" ")[2]
            if not re.fullmatch(r"http://127\.0\.0\.1:[1-9]\d*", url):
                raise RuntimeError(f"Dashboard failed to start within 10 seconds: {startup or 'no startup output'}")
            check_browser(url, channel)
        finally:
            server.terminate()


def check_hosted(channel):
    subprocess.run([sys.executable, "scripts/build_hosted_dashboard.py"], cwd=PROJECT_ROOT, check=True)
    output = PROJECT_ROOT / "sites" / "warehouse-rl-lab" / "dist"
    handler = partial(SimpleHTTPRequestHandler, directory=output)
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            check_browser(f"http://127.0.0.1:{server.server_port}", channel)
        finally:
            server.shutdown()
            worker.join()


def main():
    parser = argparse.ArgumentParser(description="Start and exercise the dashboard in a fresh browser.")
    parser.add_argument("--channel", help="Use an installed Chromium browser, such as msedge.")
    parser.add_argument("--hosted", action="store_true", help="Build and check the ChatGPT Site assets.")
    options = parser.parse_args()
    check = check_hosted if options.hosted else check_local
    check(options.channel)
    print("Dashboard smoke passed: page loaded, 25 episodes completed, and policy replay displayed.")


if __name__ == "__main__":
    main()
