"""Small compatibility routing for management callback aliases."""
from __future__ import annotations


def install(app, manager):
    async def replace_sub_pick(callback):
        # The generic picker emits *_pick while the replacement flow needs the
        # selected substitute id to be handled by the next step.
        callback.data = str(callback.data).replace(":replace_sub_pick:", ":replace_sub:")
        await manager.replace_sub(callback)

    app.dp.register_callback_query_handler(
        replace_sub_pick,
        lambda c: str(c.data or "").startswith("mgmt:") and c.data.split(":")[2] == "replace_sub_pick",
        state="*",
    )
