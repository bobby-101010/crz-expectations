import os

from pyspark.sql import SparkSession

ICEBERG_PACKAGE = "org.apache.iceberg:iceberg-spark-runtime-4.1_2.13:1.12.0"


def build_session(app_name: str) -> SparkSession:
    """Spark session with a local Iceberg catalog named `local`."""
    warehouse = os.environ.get("WAREHOUSE_DIR", "/data/warehouse")
    events = os.environ.get("SPARK_EVENTS_DIR", "/data/spark-events")
    os.makedirs(events, exist_ok=True)
    return (
        SparkSession.builder.appName(app_name)
        .master(os.environ.get("SPARK_MASTER", "local[*]"))
        .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "6g"))
        .config("spark.executor.memory", os.environ.get("SPARK_EXECUTOR_MEMORY", "2g"))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.eventLog.enabled", "true")
        .config("spark.eventLog.dir", f"file://{events}")
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
