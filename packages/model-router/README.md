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

## Current implementation

The PC-server domain now implements the versioned runtime lifecycle and a
pure route planner. It:

- routes ordinary validated text/image requests to the ready 12B runtime;
- plans drain/unload/load/health-check/route actions for exclusive 31B use;
- defers 31B while voice priority, another high-VRAM task, or a model switch
  is active;
- rejects an explicit 31B request when VRAM admission fails;
- degrades automatic escalation to 12B when its validated capability permits;
- requires failed-runtime cleanup before 12B recovery; and
- rejects unvalidated modality/context combinations.

The current measured gates mark 12B text/image and 31B text as validated.
31B image and all audio/video runtime paths remain pending. The planner does
not execute its actions or manage a process yet.
