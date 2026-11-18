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


def check_grid_playback(page):
    page.clock.install()
    page.locator("#algorithm").select_option("dqn")
    page.locator("#episodes").fill("65")
    page.locator(".monitor-settings summary").click()
    page.locator("#monitor-batch").select_option("50")
    page.evaluate("""
        () => {
            const send = window.request;
            window.request = async (path, body) => {
                if (path === "advance" && body.cursor === 50) {
                    await new Promise(resolve => { window.releaseTraining = resolve; });
                }
                return send(path, body);
            };
        }
    """)
    page.locator("#start").click()
    page.locator("#monitor-progress").scroll_into_view_if_needed()
    page.wait_for_function("typeof window.releaseTraining === 'function'", timeout=30000)
    progress = page.locator("#monitor-progress")
    duration = page.evaluate("Math.ceil(episodeGrid.group.duration)")
    page.clock.fast_forward(duration + 250)
    page.clock.run_for(64)
    before = progress.evaluate("element => element.value")
    page.clock.run_for(80)
    after = progress.evaluate("element => element.value")
    assert 0 < before < after < 1, f"Grid stalled during a delayed DQN batch: {before:.3f} → {after:.3f}"
    expect(page.locator("#monitor-status")).to_contain_text("Trained 50 of 65 episodes")

    control = page.locator("#monitor-play")
    control.click()
    expect(control).to_have_text("Follow training")
    grid_paused = progress.get_attribute("value")
    page.clock.run_for(128)
    expect(progress).to_have_attribute("value", grid_paused)
    control.click()
    expect(control).to_have_text("Pause grid")

    training_control = page.locator("#pause")
    training_control.click()
    progress.scroll_into_view_if_needed()
    expect(page.locator("#monitor-status")).to_contain_text("Training paused")
    training_paused = progress.get_attribute("value")
    page.evaluate("window.releaseTraining()")
    expect(page.locator("#monitor-status")).to_have_text("Trained 60 of 65 episodes · Training paused")
    page.clock.run_for(128)
    expect(progress).to_have_attribute("value", training_paused)
    training_control.click()
    progress.scroll_into_view_if_needed()

    expect(page.locator("#status")).to_have_text("Complete", timeout=10000)
    expect(page.locator("#monitor-range")).to_have_text("Viewing episodes 51–65")
    expect(progress).to_have_attribute("value", "1", timeout=10000)
    expect(control).to_have_text("Replay group")


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
                page.locator("#episodes").fill("25")
                page.locator("#start").click()
                expect(page.locator("#status")).to_have_text("Complete")
                expect(page.locator("#progress")).to_have_attribute("value", "25")
                expect(page.locator("#chart-figure")).to_be_visible()
                expect(page.locator("#monitor-range")).to_have_text("Viewing episodes 1–25")
                expect(page.locator(".monitor-card strong")).to_have_text(["Episode 10", "Episode 20", "Episode 25"])
                expect(page.locator("#monitor-progress")).to_have_attribute("value", "1")
                page.get_by_role("button", name=re.compile(r"^Inspect Episode 10,")).click()
                expect(page.locator("#trace-title")).to_contain_text("Training episode 10")
                page.locator("#replay").click()
                expect(page.locator("#policy-evaluation")).to_be_visible()
                expect(page.locator("#reference")).to_be_visible()
                expect(page.locator("#error")).to_be_hidden()
                page.emulate_media(reduced_motion="no-preference")
                check_grid_playback(page)
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
    print("Dashboard smoke passed: training, policy replay, and delayed DQN grid playback.")


if __name__ == "__main__":
    main()
