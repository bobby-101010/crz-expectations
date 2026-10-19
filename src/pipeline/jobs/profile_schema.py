import os
from pathlib import Path

from pyspark.sql import SparkSession


def main() -> None:
    """Print each bronze column's type per file, and mark columns that differ."""
    root = Path(os.environ.get("BRONZE_DIR", "/data/bronze"))
    spark = SparkSession.builder.master("local[1]").appName("profile_schema").getOrCreate()

    for service_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        files = sorted(service_dir.glob("*.parquet"))
        if not files:
            continue
        months = [path.stem.rsplit("_", 1)[-1] for path in files]
        schemas = [
            {field.name: field.dataType.simpleString() for field in spark.read.parquet(str(path)).schema}
            for path in files
        ]
        columns = list(dict.fromkeys(name for schema in schemas for name in schema))

        print(f"\n{service_dir.name}")
        print(f"  {'column':<24}" + "".join(f"{month:<16}" for month in months))
        for name in columns:
            types = [schema.get(name, "-") for schema in schemas]
            flag = "" if len(set(types)) == 1 else "  <-- differs"
            print(f"  {name:<24}" + "".join(f"{dtype:<16}" for dtype in types) + flag)
    spark.stop()


if __name__ == "__main__":
    main()
    