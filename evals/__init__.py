"""Remediation Evals Kit — provider-neutral harness for "which is the cheapest model that can
safely do this remediation?"

The kit scores the WHOLE loop, one stage at a time:

    detect -> diagnose -> propose -> apply -> verify -> escalate / roll back

A candidate that finds the defect and then writes an unsafe patch scores well on detection and
zero on safety, and the report says so per stage. One aggregate number would hide it.

Entry points:
    evals.harness.run          — execute candidates over a corpus
    evals.report.build_report  — scores, hard gates, risk-tier breakdown, routing ladder
    scripts/run_remediation_evals.py — CLI
"""
