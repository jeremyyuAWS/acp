"""Durable scan workflow: Discover -> Analyse (fan-out, one activity per file) -> Score.

Pure orchestration — all I/O is in activities. Mirrors ADR 0001's workflow shape;
the per-file fan-out is what Temporal scales and makes crash-resumable.
"""
from __future__ import annotations
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import discover, analyse, score


@workflow.defn
class ScanWorkflow:
    @workflow.run
    async def run(self) -> dict:
        files = await workflow.execute_activity(
            discover, start_to_close_timeout=timedelta(minutes=2))

        # fan out: one analyse activity per file, all concurrent
        raw = await asyncio.gather(*[
            workflow.execute_activity(
                analyse, f,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            for f in files
        ])

        return await workflow.execute_activity(
            score, list(raw), start_to_close_timeout=timedelta(minutes=1))
