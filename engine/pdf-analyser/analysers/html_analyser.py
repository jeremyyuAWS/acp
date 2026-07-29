"""
HTML accessibility analyser using axe-core injected into a Playwright Chromium browser.

axe-core version is pinned to 4.9.1 to prevent version drift.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from analysers.base import BaseAnalyser
from analysers.rules.html.axe_mapping import map_axe_violation
from models.manifest import AnalyserError, AnalyserResult, AnalysisJob

logger = logging.getLogger(__name__)

# Pinned axe-core version — update here only after testing
_AXE_CORE_URL = "https://cdn.jsdelivr.net/npm/axe-core@4.9.1/axe.min.js"

# axe.run() options — run all rules, return violations only
_AXE_OPTIONS = json.dumps({
    "resultTypes": ["violations"],
    "runOnly": {
        "type": "tag",
        "values": ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa", "best-practice"],
    },
})


class HtmlAnalyser(BaseAnalyser):
    ANALYSER_NAME = "html-wcag-analyser"
    ANALYSER_VERSION = "1.0.0"

    async def analyse(self, file_path: Path, job: AnalysisJob) -> AnalyserResult:
        started_at = datetime.now(timezone.utc)
        issues = []
        errors: list[AnalyserError] = []
        disabled = set(job.disabled_rule_ids)

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                context = await browser.new_context()
                page = await context.new_page()

                # Load the HTML file via file:// URL
                file_url = file_path.as_uri()
                await page.goto(file_url, wait_until="domcontentloaded", timeout=30_000)

                # Inject axe-core from CDN
                try:
                    await page.add_script_tag(url=_AXE_CORE_URL)
                except Exception:
                    # CDN unavailable — inject from a local bundled copy as fallback
                    logger.warning("CDN unavailable for axe-core — attempting local injection")
                    local_axe = Path(__file__).parent / "axe.min.js"
                    if local_axe.exists():
                        await page.add_script_tag(path=str(local_axe))
                    else:
                        raise RuntimeError(
                            "axe-core could not be loaded from CDN and no local copy found. "
                            f"Download axe-core@4.9.1 to {local_axe}"
                        )

                # Run axe
                raw_results = await page.evaluate(
                    f"() => axe.run(document, {_AXE_OPTIONS})"
                )
                await browser.close()

        except Exception as exc:
            logger.error("HTML analyser failed for %s: %s", file_path, exc, exc_info=True)
            return AnalyserResult(
                analyser_name=self.ANALYSER_NAME,
                analyser_version=self.ANALYSER_VERSION,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                succeeded=False,
                issues=[],
                errors=[AnalyserError(error_type=type(exc).__name__, message=str(exc))],
            )

        # Map axe violations → A11yIssue
        violations = raw_results.get("violations", [])
        for violation in violations:
            try:
                mapped = map_axe_violation(violation, disabled)
                issues.extend(mapped)
            except Exception as exc:
                axe_id = violation.get("id", "unknown")
                logger.warning("Failed to map axe violation '%s': %s", axe_id, exc)
                errors.append(
                    AnalyserError(
                        rule_id=axe_id,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )

        logger.info(
            "HTML analysis complete — %d violations, %d issues, %d errors",
            len(violations), len(issues), len(errors),
        )

        return AnalyserResult(
            analyser_name=self.ANALYSER_NAME,
            analyser_version=self.ANALYSER_VERSION,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            succeeded=True,
            issues=issues,
            errors=errors,
        )
