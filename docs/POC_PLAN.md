# Engineering POC
1. Validate image acquisition on allowed test pages.
2. OCR English text and return line regions with original image pixel coordinates.
3. Translate via mock baseline or server-held OpenAI-compatible key.
4. Draw Thai overlays without modifying source images.
5. Measure per-panel latency, OCR detection recall, region geometry and cloud spend.

## Gate
Backend tests pass, extension syntax passes, manual image acquisition and overlay checked. No guarantee of real manga accuracy until benchmark fixtures are assessed.
