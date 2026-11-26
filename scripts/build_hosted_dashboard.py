from pathlib import Path
from shutil import copyfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = PROJECT_ROOT / "sites" / "warehouse-rl-lab"


def main():
    output = SITE_ROOT / "dist"
    output.mkdir(parents=True, exist_ok=True)
    for filename in ("styles.css", "dashboard.js", "episode-grid.js", "warehouse-map.js"):
        copyfile(PROJECT_ROOT / "web" / filename, output / filename)
    for filename in ("agents.py", "warehouse.py", "dashboard_api.py"):
        copyfile(PROJECT_ROOT / filename, output / filename)
    for filename in ("browser-api.js", "training-worker.mjs", "site_bridge.py"):
        copyfile(PROJECT_ROOT / "web" / "hosted" / filename, output / filename)

    html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        '  <script src="/episode-grid.js" defer></script>',
        '  <script src="/browser-api.js" defer></script>\n  <script src="/episode-grid.js" defer></script>',
    )
    (output / "index.html").write_text(html, encoding="utf-8")
    print(f"Built ChatGPT Site in {output}")


if __name__ == "__main__":
    main()
