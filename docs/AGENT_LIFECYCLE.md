# Agent Lifecycle and Concurrency in Fred

Fred is not “just” LangChain + LangGraph: we also run a **long-lived backend service**.  
That means we must manage **agents as processes with lifecycles**, not just ephemeral graph runs.  
This page explains the concurrency and lifecycle pattern we use.

---

## Core Idea

- One **TaskGroup** (from [anyio](https://anyio.readthedocs.io/)) owns *all* background tasks for the app.
- Each agent has a **two-phase lifecycle**:
  1. **Cold init (fail-fast, blocking)** → build model + graph, no external I/O.
  2. **Warmup (non-blocking, background)** → connect to external systems (MCP, Knowledge-Flow) and eagerly bind tools.
- If external services are down, **startup still succeeds**; agents degrade gracefully and self-heal on first tool use.
- Shutdown is deterministic: exiting the TaskGroup cancels/awaits all children.

---

## Why This Matters

- **Deterministic startup**  
  Fred will refuse to start only if something truly core is broken (e.g. config, graph build).  
  External connectors can lag behind without blocking the app.

- **Graceful degradation**  
  If Knowledge-Flow is unavailable at boot:
  - Fred still serves chat requests.  
  - Tool calls will lazy-retry when needed.  
  - Users see reduced functionality, not a crash.

- **Leak-free shutdown**  
  Because the same task that created resources also closes them, we avoid orphan sockets or hanging retries.  
  TaskGroup exit ensures *every* child (warmup, retry loop, watchers) is cancelled and awaited.

- **Explicit separation of concerns**  
  - *Cold path*: required for the app to serve.  
  - *Warm path*: optional, can fail and retry without breaking the server.

---

## Code Walkthrough

### FastAPI `lifespan`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Lifespan enter.")
    async with anyio.create_task_group() as tg:
        app.state.tg = tg

        # --- cold init ---
        await agent_manager.load_agents(tg=tg)
        agent_manager.start_retry_loop(tg=tg)

        logger.info("✅ AgentManager fully loaded.")
        try:
            yield
        finally:
            logger.info("🧹 Lifespan exit: orderly shutdown.")
            await agent_manager.aclose()
    logger.info("✅ Shutdown complete.")
```

- One `TaskGroup` (`tg`) for the whole app.
- Cold init: fail fast if core logic is broken.
- Warmup/retry loops scheduled as TG children.

### Agent Methods

```python
async def async_init(self):
    """Cold init: build graph & model WITHOUT dialing MCP."""
    self.model = get_model(self.agent_settings.model)
    self._graph = self._build_graph()

async def async_start(self, tg: TaskGroup):
    """Warmup: connect MCP in the background (non-fatal)."""
    async def _bringup():
        try:
            await self.mcp.init()
            self.model = self.model.bind_tools(self.mcp.get_tools())
        except Exception:
            logger.info("%s: MCP unavailable; will rebind on demand.", self.name, exc_info=True)
    tg.start_soon(_bringup)

async def aclose(self):
    """Clean shutdown: close MCP client/transports from the creator task."""
    await self.mcp.aclose()
```

---

## Relation to LangChain / LangGraph

- **LangChain**: manages models, tools, runnables.  
  **Not** responsible for app-lifetime sockets, retries, or shutdown.
- **LangGraph**: executes message graphs per request.  
  **Not** responsible for long-running connectors or background bring-up.
- **Fred’s TaskGroup pattern**: fills the missing gap.  
  It is the *glue* between agent graphs and the real-world lifecycle of an always-on backend.

---

## Key Benefits

✅ Predictable startup/shutdown  
✅ Resilient to transient external failures  
✅ No orphan tasks, no dangling sockets  
✅ Compatible with LangGraph execution model  
✅ Minimal custom code (just `async_init`, `async_start`, `aclose`)

---

## When to Extend

- If an MCP client later offers its own reconnect loop → still host it inside the TaskGroup.  
- If LangGraph adds dynamic tool rebinding → you can swap internals, but the lifecycle pattern remains.  
- If you add telemetry/metrics → schedule periodic reporters as TG children.

---

## Summary

Fred uses a **structured concurrency pattern**:  
**one TaskGroup + two-phase agent lifecycle**.

This ensures agents are:
- Easy to reason about,
- Resilient under partial failure,
- Cleanly shut down,
- and not blocked by external services at startup.

This is not “reinventing LangChain” — it’s the missing operational layer that makes Fred a production-grade backend.
