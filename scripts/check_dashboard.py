import argparse
import csv
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


def exported_episodes(page):
    with page.expect_download() as downloaded:
        page.locator("#export").click()
    with downloaded.value.path().open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def check_stocked_racks(page):
    page.locator("#environment").select_option("stocked_racks")
    for field, value in (("algorithm", "q_learning"), ("traffic", "none"), ("mission", "deliver")):
        expect(page.locator(f"#{field}")).to_have_value(value)
        expect(page.locator(f"#{field}")).to_be_disabled()

    page.locator("#start").click()
    expect(page.locator("#status")).to_have_text("Complete")
    page.locator("#replay").click()
    expect(page.locator("#policy-evaluation")).to_contain_text("2 across stocked-rack orders")
    page.locator("#reference").click()
    expect(page.locator("#trace-limit")).to_have_text("0 / 14")
    expect(page.locator("#order-status")).to_contain_text("Tote empty")
    item = "CARTON" if "Order CARTON" in page.locator("#order-status").inner_text() else "REFILL"
    pickup_tick, bay = (5, "A") if item == "CARTON" else (10, "B")
    page.locator("#scrub").fill(str(pickup_tick))
    expect(page.locator("#event .event-chip")).to_have_text(["Wait", f"Picked up {item}"])
    expect(page.locator("#order-status")).to_contain_text(f"Tote {item}")
    expect(page.locator("#order-status")).to_contain_text(f"{bay} {item} ×0")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("0")
    page.locator("#scrub").fill("14")
    expect(page.locator("#event")).to_contain_text("Delivered")
    expect(page.locator("#order-status")).to_contain_text("Tote empty")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("+100")

    records = exported_episodes(page)
    assert {record["order"] for record in records} == {"CARTON", "REFILL"}
    assert {record["environment"] for record in records} == {"stocked_racks"}
    assert all(record["pickup_tick"] for record in records if record["outcome"] == "delivered")

    page.locator("#environment").select_option("navigation")
    expect(page.locator("#traffic")).to_have_value("patrol")
    expect(page.locator("#mission")).to_have_value("return")
    expect(page.locator("#mission")).to_be_enabled()


def check_charging_dock(page):
    page.locator("#environment").select_option("charging_dock")
    expect(page.locator("#trace-limit")).to_have_text("0 / 16")
    expect(page.locator("#battery-status")).to_have_text("Battery 12 / 14 · Charging ticks 0")
    page.locator("#scrub").fill("2")
    expect(page.locator("#event .event-chip")).to_have_text(["Wait", "Charged +1"])
    expect(page.locator("#battery-status")).to_have_text("Battery 14 / 14 · Charging ticks 2")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("0")
    page.locator("#scrub").fill("16")
    expect(page.locator("#battery-status")).to_have_text("Battery 0.8 / 14 · Charging ticks 2")
    expect(page.locator("#event")).to_contain_text("Delivered")
    page.locator("#charge-preview").select_option("full")
    expect(page.locator("#trace-limit")).to_have_text("0 / 14")
    page.locator("#scrub").fill("1")
    expect(page.locator("#battery-status")).to_have_text("Battery 13 / 14 · Charging ticks 0")

    page.locator("#start").click()
    expect(page.locator("#status")).to_have_text("Complete")
    expect(page.locator("#progress")).to_have_attribute("value", "13")
    page.locator("#replay").click()
    expect(page.locator("#policy-evaluation")).to_contain_text("4 across orders and starting charges")
    expect(page.locator("#policy-evaluation")).to_contain_text("Battery depletions")
    page.locator("#reference").click()
    expect(page.locator("#trace-limit")).to_have_text("0 / 16")
    records = exported_episodes(page)
    assert len(records) == 13
    assert {record["battery_case"] for record in records} == {"low", "full"}
    assert {record["pretraining_episodes"] for record in records} == {"12"}
    assert {record["target_episodes"] for record in records} == {"13"}
    assert all(record["end_charge"] and record["charge_ticks"] for record in records)

    page.locator("#training-start").select_option("scratch")
    page.locator("#start").click()
    expect(page.locator("#status")).to_have_text("Complete")
    expect(page.locator("#progress")).to_have_attribute("value", "25")
    assert {record["pretraining_episodes"] for record in exported_episodes(page)} == {"0"}


def check_pack_and_stage(page):
    page.locator("#environment").select_option("pack_and_stage")
    expect(page.locator("#battery-status")).to_have_text("Battery 16 / 16 · Charging ticks 0")
    expect(page.locator("#trace-limit")).to_have_text("0 / 17")
    expect(page.locator("#map")).to_have_attribute(
        "aria-label", re.compile(r"Packing station at column H, row 6\. Outbound staging at column I, row 6\."),
    )
    page.locator("#scrub").fill("14")
    expect(page.locator("#order-status")).to_contain_text("Tote CARTON")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("0")
    page.locator("#scrub").fill("16")
    expect(page.locator("#event .event-chip")).to_have_text(["Wait", "Packed CARTON"])
    expect(page.locator("#order-status")).to_contain_text("Carton CARTON packed")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("0")
    page.locator("#scrub").fill("17")
    expect(page.locator("#event")).to_contain_text("Staged for shipment")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("+100")
    page.locator("#charge-preview").select_option("low")
    expect(page.locator("#trace-limit")).to_have_text("0 / 19")

    page.locator("#training-start").select_option("warm")
    expect(page.locator("#training-start-note")).to_contain_text("practice packing without battery limits")
    page.locator("#start").click()
    expect(page.locator("#status")).to_have_text("Complete")
    expect(page.locator("#progress")).to_have_attribute("value", "13")
    page.locator("#replay").click()
    expect(page.locator("#policy-evaluation")).to_contain_text("4 across orders and starting charges")
    page.locator("#reference").click()
    expect(page.locator("#trace-limit")).to_have_text("0 / 19")
    records = exported_episodes(page)
    assert {record["pretraining_episodes"] for record in records} == {"12"}
    assert {record["environment"] for record in records} == {"pack_and_stage"}
    assert {record["initial_charge"] for record in records} == {"14", "16"}
    assert all("pack_tick" in record for record in records)


def check_multiple_layouts(page):
    page.locator("#environment").select_option("multiple_layouts")
    expect(page.locator("#algorithm")).to_have_value("dqn")
    expect(page.locator("#training-start-setting")).to_be_hidden()
    page.locator("#preview-floor").select_option("parallel")
    expect(page.locator("#trace-title")).to_contain_text("Parallel aisles")
    expect(page.locator("#trace-limit")).to_have_text("0 / 17")
    page.locator("#preview-floor").select_option("cross_aisle")
    expect(page.locator("#trace-limit")).to_have_text("0 / 15")
    expect(page.locator("#map")).to_have_attribute(
        "aria-label", re.compile(r"Offset cross-aisle floor\. Tick 0\. Robot at column B, row 7\."),
    )
    page.locator("#scrub").fill("15")
    expect(page.locator("#event")).to_contain_text("Staged for shipment")

    page.locator("#layout-training").select_option("mixed")
    page.locator("#start").click()
    expect(page.locator("#status")).to_have_text("Complete")
    original_card = page.get_by_role("button", name=re.compile(r"^Inspect Episode 10, .*Original$"))
    parallel_card = page.get_by_role("button", name=re.compile(r"^Inspect Episode 25, .*Parallel aisles$"))
    for card, floor in ((original_card, "Original"), (parallel_card, "Parallel aisles")):
        card.click()
        expect(page.locator("#trace-title")).to_contain_text(floor)
        expect(page.locator("#map")).to_have_attribute("aria-label", re.compile(rf"^{floor} floor\."))
    shelf_sample = """canvas => Array.from(canvas.getContext("2d").getImageData(
        Math.floor(172 / 500 * canvas.width), Math.floor(128 / 500 * canvas.height), 1, 1
    ).data)"""
    assert original_card.locator("canvas").evaluate(shelf_sample) != parallel_card.locator("canvas").evaluate(shelf_sample)

    records = exported_episodes(page)
    assert {record["layout"] for record in records} == {"original", "parallel"}
    assert {record["layout_training"] for record in records} == {"mixed"}
    expect(page.locator("#evaluation-floor")).to_have_value("cross_aisle")
    page.locator("#replay").click()
    expect(page.locator("#policy-evaluation")).to_contain_text("Offset cross-aisle (unseen in training)")
    expect(page.locator("#policy-evaluation")).to_contain_text("4 across orders and starting charges")
    page.locator("#reference").click()
    expect(page.locator("#trace-title")).to_contain_text("Offset cross-aisle")
    expect(page.locator("#trace-limit")).to_have_text("0 / 19")
    page.locator("#evaluation-floor").select_option("parallel")
    expect(page.locator("#reference")).to_be_hidden()
    page.locator("#replay").click()
    expect(page.locator("#policy-evaluation")).to_contain_text("Parallel aisles (seen in training)")
    assert exported_episodes(page) == records

    page.locator("#layout-training").select_option("original")
    page.locator("#start").click()
    expect(page.locator("#status")).to_have_text("Complete")
    records = exported_episodes(page)
    assert {record["layout"] for record in records} == {"original"}
    assert {record["layout_training"] for record in records} == {"original"}
    page.locator("#replay").click()
    expect(page.locator("#policy-evaluation")).to_contain_text("Parallel aisles (unseen in training)")


def check_shared_aisles(page):
    page.locator("#environment").select_option("shared_aisles")
    expect(page.locator("#algorithm")).to_have_value("dqn")
    expect(page.locator("#layout-training-setting")).to_be_hidden()
    expect(page.locator("#scripted-robot-key")).to_be_visible()
    expect(page.locator("#map")).to_have_attribute(
        "aria-label", re.compile(r"Robot at column B, row 6\. Replenishment AMR at column E, row 5\."),
    )
    preview = page.locator("#aisle-preview")
    for scenario, tick, messages, tally in (
        ("same_cell", "8", ["Same-cell request", "Order AMR denied"], "Denials 1 order / 0 replenishment · Stall ticks 0"),
        ("swap", "9", ["Head-on swap prevented", "Order AMR denied", "Replenishment AMR denied"],
         "Denials 1 order / 1 replenishment · Stall ticks 1"),
        ("occupied", "9", ["Aisle cell occupied", "Replenishment AMR denied"],
         "Denials 0 order / 1 replenishment · Stall ticks 1"),
    ):
        preview.select_option(scenario)
        expect(page.locator("#charge-preview-setting")).to_be_hidden()
        page.locator("#scrub").fill(tick)
        expect(page.locator("#event .event-chip")).to_contain_text(messages)
        expect(page.locator("#aisle-status")).to_contain_text(tally)
        expect(page.locator('[data-term="Delivery"]')).to_have_text("0")
    page.locator("#scrub").fill("10")
    expect(page.locator("#map")).to_have_attribute(
        "aria-label", re.compile(r"Robot at column G, row 6\. Replenishment AMR at column F, row 6\."),
    )
    preview.select_option("carton")
    expect(page.locator("#charge-preview-setting")).to_be_visible()
    page.locator("#scrub").fill("14")
    expect(page.locator("#event")).to_contain_text("Bay replenished")
    page.locator("#scrub").fill("17")
    expect(page.locator("#aisle-status")).to_contain_text("Parked")

    page.locator("#start").click()
    expect(page.locator("#status")).to_have_text("Complete")
    expect(page.locator("#stall-metric")).to_be_visible()
    page.get_by_role("button", name=re.compile(r"^Inspect Episode 25,")).click()
    expect(page.locator("#aisle-status")).to_be_visible()
    page.locator("#replay").click()
    expect(page.locator("#policy-evaluation")).to_contain_text("8 across orders, starting charges, and release times")
    expect(page.locator("#policy-evaluation")).to_contain_text("Replenishment AMR parked")
    page.locator("#reference").click()
    expect(page.locator("#trace-limit")).to_have_text("0 / 19")
    page.locator("#scrub").fill("19")
    expect(page.locator("#event")).to_contain_text("Staged for shipment")
    expect(page.locator("#aisle-status")).to_contain_text("Parked")
    records = exported_episodes(page)
    assert {record["release_tick"] for record in records} == {"7", "10"}
    assert {record["environment"] for record in records} == {"shared_aisles"}
    assert any(int(record["stall_ticks"]) > 0 for record in records)
    assert all(record["primary_denials"] and record["scripted_denials"] for record in records)
    page.locator("#environment").select_option("navigation")
    expect(page.locator("#aisle-preview-setting")).to_be_hidden()
    expect(page.locator("#scripted-robot-key")).to_be_hidden()


def check_two_learning_robots(page):
    page.locator("#environment").select_option("two_learning_robots")
    expect(page.locator("#algorithm")).to_have_value("ippo")
    expect(page.locator("#second-robot-key")).to_be_visible()
    expect(page.locator("#fleet-first-status")).to_contain_text("AMR 1 · CARTON")
    expect(page.locator("#fleet-second-status")).to_contain_text("AMR 2 · REFILL")
    page.locator("#scrub").fill("15")
    expect(page.locator("#fleet-second-status")).to_contain_text("Order staged")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("+50")
    page.locator("#scrub").fill("16")
    expect(page.locator("#fleet-second-status")).to_contain_text("Exited through staging")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("0")
    page.locator("#scrub").fill("17")
    expect(page.locator("#event")).to_contain_text("Both orders staged")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("+50")

    for algorithm in ("ippo", "mappo"):
        page.locator("#algorithm").select_option(algorithm)
        page.locator("#start").click()
        expect(page.locator("#status")).to_have_text("Complete", timeout=15000)
        expect(page.locator("#fleet-waits-metric")).to_be_visible()
        page.get_by_role("button", name=re.compile(r"^Inspect Episode 25,")).click()
        expect(page.locator("#fleet-second-status")).to_be_visible()
        records = exported_episodes(page)
        assert {record["algorithm"] for record in records} == {algorithm}
        assert {record["second_order"] for record in records} == {"CARTON", "REFILL"}
        assert all(record["first_denials"] and record["second_waits"] for record in records)
        page.locator("#fleet-case").select_option("4")
        page.locator("#fleet-policy-mode").select_option("greedy")
        page.locator("#replay").click()
        expect(page.locator("#policy-evaluation")).to_contain_text("/8 trials")
        page.locator("#reference").click()
        expect(page.locator("#trace-title")).to_contain_text("Fastest joint route")
        expect(page.locator("#trace-limit")).to_have_text("0 / 22")
        expect(page.locator("#fleet-first-status")).to_contain_text("AMR 1 · REFILL")
        page.locator("#fleet-policy-mode").select_option("sampled")
        expect(page.locator("#reference")).to_be_hidden()
        page.locator("#replay").click()
        expect(page.locator("#policy-evaluation")).to_contain_text("/32 trials")
        assert exported_episodes(page) == records
    page.locator("#environment").select_option("navigation")
    expect(page.locator("#algorithm")).to_have_value("q_learning")
    expect(page.locator("#second-robot-key")).to_be_hidden()


def check_continuous_fulfillment(page):
    page.locator("#environment").select_option("continuous_fulfillment")
    expect(page.locator("#trace-title")).to_contain_text("burst workload")
    expect(page.locator("#trace-limit")).to_have_text("0 / 80")
    expect(page.locator("#shift-stock")).to_contain_text("CARTON 1 (1 reserved)")
    page.locator("#scrub").fill("14")
    expect(page.locator("#shift-packing")).to_contain_text("FIFO queue #1, #2")
    page.locator("#scrub").fill("15")
    expect(page.locator("#shift-packing")).to_contain_text("Packing #1 · 3 ticks left · FIFO queue #2")
    page.locator("#scrub").fill("18")
    expect(page.locator("#shift-packing")).to_contain_text("Packing idle · FIFO queue #2")
    page.locator("#scrub").fill("19")
    expect(page.locator("#shift-packing")).to_contain_text("Packing #2 · 3 ticks left")
    expect(page.locator('[data-term="Delivery"]')).to_have_text("+50")
    page.locator("#scrub").fill("80")
    expect(page.locator("#shift-orders")).to_contain_text("Released 12 · Staged 4 · Backlog 8")
    page.get_by_text("Released orders", exact=True).click()
    expect(page.locator("#shift-order-list li")).to_have_count(12)
    expect(page.locator("#shift-order-list li").last).to_contain_text("Awaiting assignment")

    page.locator("#algorithm").select_option("mappo")
    page.locator("#start").click()
    expect(page.locator("#status")).to_have_text("Complete", timeout=20000)
    expect(page.locator("#shift-throughput-metric")).to_be_visible()
    expect(page.locator("#completion-label")).to_have_text("Orders staged")
    records = exported_episodes(page)
    assert {record["workload"] for record in records} == {"paced", "burst"}
    assert all(int(row["released"]) == int(row["backlog"]) + int(row["orders_completed"]) for row in records)
    expect(page.locator("#fleet-case")).to_have_value("2")
    page.locator("#replay").click()
    expect(page.locator("#policy-evaluation")).to_contain_text("Burst workload · 8 trials")
    expect(page.locator("#policy-evaluation")).to_contain_text("Dispatch reference staged 4/12")
    page.locator("#reference").click()
    expect(page.locator("#trace-title")).to_contain_text("Centralized dispatch reference")
    page.locator("#fleet-case").select_option("0")
    page.locator("#fleet-policy-mode").select_option("greedy")
    page.locator("#replay").click()
    expect(page.locator("#policy-evaluation")).to_contain_text("Paced workload · 2 trials")
    expect(page.locator("#policy-evaluation")).to_contain_text("Dispatch reference staged 4/6")
    assert exported_episodes(page) == records
    page.locator("#environment").select_option("navigation")
    expect(page.locator("#shift-panel")).to_be_hidden()


def check_browser(url, channel):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel)
        try:
            page = browser.new_page(viewport={"width": 1536, "height": 900}, reduced_motion="reduce")
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
                floor = page.locator(".floor").bounding_box()
                inspector = page.locator(".floor-inspector").bounding_box()
                assert floor and inspector, "Expected the warehouse floor and transition inspector"
                assert inspector["y"] >= floor["y"] + floor["height"], "Expected the inspector below the warehouse floor"
                legend = page.locator(".floor-panel > .floor-content + .floor-legend")
                map_key = legend.locator("summary")
                expect(map_key).to_be_visible()
                expect(legend.locator("ul")).to_be_hidden()
                map_key.press("Enter")
                expect(legend.locator("ul")).to_be_visible()
                map_key.press("Space")
                expect(legend.locator("ul")).to_be_hidden()
                scrubber = page.get_by_role("slider", name="Trace tick")
                scrubber.press("End")
                expect(page.locator("#event")).to_contain_text("Returned to base")
                expect(page.locator("#map")).to_have_attribute("aria-label", re.compile(r"Parcel at the dock"))
                expect(page.locator("#reward-terms [data-term='Delivery']")).to_have_text("+100")
                expect(page.locator('#algorithm optgroup[label="Hybrid"] option[value="ppo"]')).to_have_count(1)
                selected = page.get_by_role("button", name=re.compile(r"^Inspect Episode 10,"))
                for algorithm in ("q_learning", "ppo"):
                    page.locator("#algorithm").select_option(algorithm)
                    page.locator("#episodes").fill("25")
                    page.locator("#start").click()
                    expect(page.locator("#status")).to_have_text("Complete")
                    expect(page.locator("#progress")).to_have_attribute("value", "25")
                    expect(page.locator("#chart-figure")).to_be_visible()
                    expect(page.locator("#monitor-range")).to_have_text("Viewing episodes 1–25")
                    expect(page.locator(".monitor-card strong")).to_have_text(["Episode 10", "Episode 20", "Episode 25"])
                    expect(page.locator("#monitor-progress")).to_have_attribute("value", "1")
                    selected.click()
                    expect(selected).to_have_attribute("aria-pressed", "true")
                    expect(page.locator("#trace-title")).to_contain_text("Training episode 10")
                    page.locator("#replay").click()
                    expect(page.locator("#policy-evaluation")).to_be_visible()
                    expect(selected).to_have_attribute("aria-pressed", "false")
                    page.locator("#reference").click()
                    expect(page.locator("#trace-title")).to_contain_text("Fastest collision-free route")
                    expect(page.locator("#error")).to_be_hidden()
                map_key.click()
                expect(page.locator("#map-key-reference")).to_be_visible()
                map_key.click()
                page.locator("#algorithm").select_option("q_learning")
                check_stocked_racks(page)
                check_charging_dock(page)
                check_pack_and_stage(page)
                check_multiple_layouts(page)
                map_key.click()
                check_shared_aisles(page)
                check_two_learning_robots(page)
                map_key.click()
                check_continuous_fulfillment(page)
                expect(page.locator("#error")).to_be_hidden()
                page.close()
                grid_page = browser.new_page(viewport={"width": 1536, "height": 900}, reduced_motion="no-preference")
                grid_page.set_default_timeout(5000)
                grid_page.on("pageerror", lambda error: errors.append(str(error)))
                grid_page.on("response", record_response)
                grid_page.goto(url)
                expect(grid_page.locator("#status")).to_have_text("Ready", timeout=25000)
                check_grid_playback(grid_page)
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
    print("Dashboard smoke passed for V0 through V7, including PPO replay and delayed DQN grid playback.")


if __name__ == "__main__":
    main()
