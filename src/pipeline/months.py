from datetime import date


def month_bounds(month: str) -> tuple[date, date]:
    """'2025-01' -> (2025-01-01, 2025-02-01). The end date is excluded."""
    year, mon = (int(part) for part in month.split("-"))
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return start, end


def month_range(start: str, end: str) -> list[str]:
    """'2024-11', '2025-02' -> ['2024-11', '2024-12', '2025-01', '2025-02']."""
    current, _ = month_bounds(start)
    last, _ = month_bounds(end)
    if current > last:
        raise ValueError(f"start {start} is after end {end}")
    months = []
    while current <= last:
        months.append(f"{current.year}-{current.month:02d}")
        _, current = month_bounds(months[-1])
    return months
