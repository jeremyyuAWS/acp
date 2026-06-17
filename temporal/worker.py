"""acp Temporal worker — hosts the scan workflow + activities on task queue 'acp-scan'."""
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from activities import analyse, discover, score
from workflow import ScanWorkflow

TASK_QUEUE = "acp-scan"


async def main():
    client = await Client.connect("localhost:7233")
    async with Worker(client, task_queue=TASK_QUEUE,
                      workflows=[ScanWorkflow], activities=[discover, analyse, score]):
        print(f"worker ready on '{TASK_QUEUE}' (ctrl-c to stop)", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
