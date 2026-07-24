# Salon receptionist

## Scope

The first salon slice treats `salon.call.start` from the loopback Web QA
portal as an incoming call. It is deliberately text-first: telephony ingress
and speech synthesis are adapters that can be attached after the reservation
rules pass without changing the domain service.

The receptionist persona is **수아**, the reservation assistant for
**윤슬 헤어**. It may:

- explain configured services, prices, hours, location, parking, and the
  cancellation policy;
- find a qualified, non-overlapping staff slot;
- create, change, or cancel a reservation only after the caller confirms;
- ask for missing name, phone, service, date/time, staff, or reservation code;
- reject unrelated requests instead of improvising an answer.

The committed demonstration policy is
[`configs/salon-booking.json`](../configs/salon-booking.json). It contains no
real customer data and can be replaced with another closed-schema policy.
Business rules stay in the domain service rather than the prompt or browser.

## Flow

`salon.call.start` creates an isolated call state and returns the greeting.
Each `salon.call.message` is passed through the bounded intent/slot parser and
the reservation domain service. Proposed mutations enter a confirmation
state. An affirmative response atomically updates the file and emits both
`salon.reservation.updated` and `salon.owner.notification`. A rejection clears
the proposal without writing. `salon.call.end` closes the simulated call.

The transaction engine is deterministic and does not reserve GPU memory. An
optional Gemma 4 adapter answers otherwise-unmatched salon FAQs through a
strict two-field JSON schema. It receives only the committed policy and the
question, and it never receives authority to write the schedule. If the
runtime is unavailable or its output fails validation, the text workflow
continues with a bounded fallback. The domain service remains the source of
truth for:

- past dates and the 90-day booking horizon;
- closed days, business hours, and 30-minute slot alignment;
- service duration and staff qualification;
- overlapping bookings, duplicate phone/time bookings, and staff selection;
- reservation-code and phone verification for changes and cancellation.

## Storage and recovery

| Purpose | Windows path | WSL path |
|---|---|---|
| Active reservation table | `E:\Data\LocalVoiceAgent\salon\reservations.json` | `/mnt/e/Data/LocalVoiceAgent/salon/reservations.json` |
| Local fast-recovery copies | `D:\LocalBackup\LocalVoiceAgent\salon\<timestamp>` | `/mnt/d/LocalBackup/LocalVoiceAgent/salon/<timestamp>` |
| Policy | `C:\Dev\Repos\local-voice-agent\configs\salon-booking.json` | `/mnt/c/Dev/Repos/local-voice-agent/configs/salon-booking.json` |

The active table is a versioned JSON document written through same-directory
atomic replacement. Before every mutation, the store writes an append-only
timestamped copy and a recovery manifest containing the recoverable time,
source path, size, and SHA-256 digest. Existing backup containers are never
overwritten or automatically pruned.

Latest local recovery point: inspect the newest successful
`recovery-manifest.json` under the D: root. Before the first reservation
mutation there is no local recovery artifact because the empty table is
reconstructible.

Latest off-machine recovery point: **not configured for this feature**.
This is an explicit durability gap. Do not claim off-machine recovery until a
separate job copies verified D: artifacts and records its own manifest.

## Notification and privacy

Connected authenticated Android and Web QA sessions receive
`salon.owner.notification`. Customer phone numbers are masked in snapshots
and notification payloads. The complete phone number exists only in the
active reservation file and its protected recovery copies because it is
needed to authenticate a caller's change or cancellation.

Android posts a local notification through the
`salon_reservations` channel when notification permission is available. A
disconnected client can refresh the reservation table after reconnecting;
durable exactly-once notification delivery is outside this first slice.
Raw call audio is not stored.

## Automated coverage

[`benchmarks/tool-cases/salon-reservation-cases.json`](../benchmarks/tool-cases/salon-reservation-cases.json)
contains the text-first conversation catalog. Domain, coordinator, protocol,
API, cross-session notification, and catalog tests cover successful booking,
missing fields, rejection, modification, cancellation, duplicate booking,
staff overlap, closed days, outside-hours and misaligned slots, FAQs, and
out-of-scope requests.

Physical user QA and TTS listening QA are intentionally performed only after
the text path, model smoke, and automated regressions pass.

## Optional model and TTS adapters

`LVA_SALON_LLM_ENABLED=1` enables the loopback-only structured FAQ adapter.
The production reservation parser still handles every mutation. On
2026-07-25, a `gpuq`-managed Gemma 4 12B run classified four supported salon
questions and two unrelated questions correctly (6/6). The cold first
request took 2,435.599 ms; the following requests took 206.110–471.006 ms.
The scheduler observed 14,682 MiB peak total GPU use and the wrapper stopped
the owned vLLM process after the evidence was written.

`LVA_SALON_TTS_ENABLED=1` attaches the existing Qwen3-TTS 1.7B worker to each
completed salon text response. One assistant response is synthesized as one
unit to avoid sentence-boundary voice changes. The gateway applies a 24 ms
release and a 200 ms final pause, then emits the existing ordered
`audio.output.*` events. A TTS failure does not invalidate a successful text
or reservation result.

The live two-sample TTS smoke passed, but full synthesis completed in
8,460.720 ms for the greeting and 5,096.497 ms for the confirmation. These
are measured limitations, not first-audio streaming measurements. Subjective
voice quality and telephone responsiveness remain user QA.

The final authenticated live gateway smoke also passed
WebSocket → scoped Gemma FAQ → Qwen3-TTS → ordered PCM completion. Greeting
end-to-end completion took 11,252.553 ms with 13 chunks; the previously
unmatched salon FAQ took 7,827.962 ms with nine chunks and did not use the
model-unavailable fallback. This verifies wiring, not acceptable interactive
latency.
