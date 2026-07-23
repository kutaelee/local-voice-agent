# Model router

Selects a runtime/model without directly loading GPU weights.

Primary states:

`UNLOADED -> LOADING -> HEALTH_CHECKING -> READY -> DRAINING -> UNLOADING`

Failure enters `FAILED`, persists evidence, and invokes the configured
fallback transition. The default route is the 12B W4A16 model. The 31B route
is requested for complex planning, recovery, long-log/diff analysis, repeated
12B tool failure, high-risk review, or explicit user selection.

Routing considers current VRAM, reserved first-audio capacity, queue state,
model capability, context size, and whether a model transition is already in
progress. It emits model-switch events but has no Android dependency.
