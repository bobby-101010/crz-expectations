"""Export the status page's data from the warehouse, then render `site/index.html`."""

import os
from pathlib import Path

from pyspark.sql import SparkSession

from pipeline.metrics import load_catalog
from pipeline.registry import Entry, load_registry
from pipeline.session import build_session
from pipeline.site import export
from pipeline.site.render import load, render

ROOT = Path(__file__).resolve().parents[3]
REPO_URL = "https://github.com/bobby-101010/crz-expectations"


def site_dir() -> Path:
    return Path(os.environ.get("SITE_DIR", ROOT / "site"))


def render_page(folder: Path) -> Path:
    """`data/*.json` in the site folder -> `index.html` beside it. Needs no Spark."""
    page = folder / "index.html"
    page.write_text(
        render(load(folder / "data"), essay_exists=(ROOT / "docs" / "essay.md").exists())
    )
    return page


def run(
    spark: SparkSession, entries: list[Entry] | None = None, folder: Path | None = None
) -> Path:
    """Export and render. Returns the page's path."""
    folder = folder or site_dir()
    catalog = load_catalog()
    entries = load_registry(catalog=catalog) if entries is None else entries
    repo_url = os.environ.get("REPO_URL", REPO_URL)
    export.write(export.collect(spark, entries, catalog, repo_url), folder / "data")
    return render_page(folder)


def main() -> None:
    spark = build_session("site")
    page = run(spark)
    spark.stop()
    print(f"{page}  {page.stat().st_size / 1000:.0f} kB")


if __name__ == "__main__":
    main()
