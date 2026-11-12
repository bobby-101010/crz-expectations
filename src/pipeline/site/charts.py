"""Small charts as inline SVG strings. No JavaScript, and colors come from the page's CSS."""

from html import escape


def fmt(value: float, unit: str | None) -> str:
    """A number in its unit, the way the page shows it."""
    if unit == "percent":
        return f"{value:+.2f}%"
    if unit == "percent_of_days":
        return f"{value:.1f}% of days"
    if unit == "ratio":
        return f"{value:.2f}"
    return f"{value:,.0f}"


def range_bar(observed: float | None, low: float, high: float, unit: str | None) -> str:
    """The expected range as a band on an axis, with a marker where the observed value fell."""
    width, height, pad = 320, 56, 16
    values = [low, high] + ([observed] if observed is not None else [])
    span = (max(values) - min(values)) or 1.0
    left, right = min(values) - 0.25 * span, max(values) + 0.25 * span

    def x(value: float) -> float:
        return round(pad + (value - left) / (right - left) * (width - 2 * pad), 1)

    if observed is None:
        label = f"Expected {fmt(low, unit)} to {fmt(high, unit)}. Not observed yet."
        marker = ""
    else:
        label = f"Observed {fmt(observed, unit)}. Expected {fmt(low, unit)} to {fmt(high, unit)}."
        marker = (
            f'<line class="marker" x1="{x(observed)}" x2="{x(observed)}" y1="8" y2="36"/>'
            f'<circle class="marker-dot" cx="{x(observed)}" cy="22" r="5"/>'
        )
    return (
        f'<svg class="range-bar" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(label)}"><title>{escape(label)}</title>'
        f'<line class="axis" x1="{pad}" x2="{width - pad}" y1="22" y2="22"/>'
        f'<rect class="band" x="{x(low)}" y="14" width="{round(x(high) - x(low), 1)}" height="16" '
        f'rx="3"/>{marker}'
        f'<text class="tick" x="{x(low)}" y="50" text-anchor="middle">'
        f"{escape(fmt(low, unit))}</text>"
        f'<text class="tick" x="{x(high)}" y="50" text-anchor="middle">'
        f"{escape(fmt(high, unit))}</text></svg>"
    )


def series_chart(
    window: list[float],
    comparison: list[float] | None = None,
    band: list[tuple[float, float] | None] | None = None,
    description: str = "",
) -> str:
    """Daily values over the window as a line.

    The comparison window is a dashed line behind it, and a baseline band is shaded.
    """
    width, height, pad = 320, 96, 6
    lows = [pair[0] for pair in band or [] if pair]
    highs = [pair[1] for pair in band or [] if pair]
    everything = [*window, *(comparison or []), *lows, *highs]
    if not everything:
        return ""
    bottom, top = min(everything), max(everything)
    spread = (top - bottom) or 1.0
    longest = max(len(window), len(comparison or []), len(band or []), 2)

    def point(index: int, value: float) -> str:
        px = pad + index / (longest - 1) * (width - 2 * pad)
        py = height - pad - (value - bottom) / spread * (height - 2 * pad)
        return f"{px:.1f},{py:.1f}"

    def line(values: list[float], css: str) -> str:
        if not values:
            return ""
        if len(values) == 1:
            px, py = point(0, values[0]).split(",")
            return f'<circle class="{css}-dot" cx="{px}" cy="{py}" r="3"/>'
        points = " ".join(point(i, v) for i, v in enumerate(values))
        return f'<polyline class="{css}" points="{points}"/>'

    shaded = ""
    if band and all(band):
        upper = [point(i, pair[1]) for i, pair in enumerate(band)]
        lower = [point(i, pair[0]) for i, pair in reversed(list(enumerate(band)))]
        shaded = f'<polygon class="baseline-band" points="{" ".join(upper + lower)}"/>'
    return (
        f'<svg class="series" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(description)}"><title>{escape(description)}</title>'
        f"{shaded}{line(comparison or [], 'comparison')}{line(window, 'window')}</svg>"
    )
