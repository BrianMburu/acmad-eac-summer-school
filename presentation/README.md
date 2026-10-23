# Sudan JJA 2025 forecast-risk deck

A 12-slide, 16:9 presentation that connects the four analyses in this
repository: local rainfall thresholds (A), forecast threshold counts (B),
start-date timing (C), and regional probability/frequency maps (D).

## Files

- `JJA2025_Sudan_forecast_risk.pptx` — the finished deck.
- `build_deck.py` — reproducible `python-pptx` builder. It reads the committed
  CSVs and PNGs under `out/` and writes the deck.

## Build

```bash
uv run --with python-pptx python presentation/build_deck.py
```

## Checks

```bash
uv run pytest
uvx ruff check scripts tests presentation
```

## Render QA

LibreOffice is used only for visual QA. The deck itself is built by
`python-pptx`.

```bash
libreoffice --headless --convert-to pdf presentation/JJA2025_Sudan_forecast_risk.pptx
pdftocairo -png -r 110 JJA2025_Sudan_forecast_risk.pdf slide
```

## Repository

- Code and outputs: <https://github.com/BrianMburu/acmad-eac-summer-school>
- Annotated final tag: <https://github.com/BrianMburu/acmad-eac-summer-school/tree/final>
