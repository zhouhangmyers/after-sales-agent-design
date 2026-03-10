from __future__ import annotations

import asyncio
import time


async def fake_tool_call(name: str, delay: int) -> str:
    await asyncio.sleep(delay)
    return f"{name} finished"


async def main() -> None:
    start = time.perf_counter()

    results = await asyncio.gather(
        fake_tool_call("tool-call-1", 2),
        fake_tool_call("tool-call-2", 2),
        fake_tool_call("tool-call-3", 1),
    )

    elapsed = time.perf_counter() - start
    print("results:", results)
    print(f"elapsed: {elapsed:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
