import os

from pyspark.sql import SparkSession

ICEBERG_PACKAGE = "org.apache.iceberg:iceberg-spark-runtime-4.1_2.13:1.12.0"

def build_session(app_name: str) -> SparkSession:
    """Spark session with a local Iceberg catalog named `local`."""
    warehouse = os.environ.get("WAREHOUSE_DIR", "/data/warehouse")
    return (
        SparkSession.builder.appName(app_name)
        .master(os.environ.get("SPARK_MASTER", "local[*]"))
        .config("spark.jars.packages", ICEBERG_PACKAGE)
        .config("spark.jars.ivy", os.environ.get("IVY_DIR", "/opt/ivy"))
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.sql.catalog.local", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.local.type", "hadoop")
        .config("spark.sql.catalog.local.warehouse", warehouse)
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )
