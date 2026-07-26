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
The demonstration menu contains ten priced services grouped into cut, color,
perm, and clinic categories. Each service declares its duration, aliases, and
qualified staff so availability answers are calculated from the same policy
shown in the QA portal.

## Flow

`salon.call.start` creates an isolated call state and returns the greeting.
Each `salon.call.message` is passed to the Gemma conversation harness with the
persona, recent dialogue, committed policy, current time, and bounded call
state. Gemma produces the customer-facing reply plus a closed-schema action
and optional slots. Application code does not compose the normal dialogue.
The default salon runtime is the pinned Gemma 4 E4B mobile-QAT checkpoint.
Code recommends only a bounded intent token when the caller explicitly says
book, check availability, modify, or cancel; E4B still authors the complete
spoken reply. This keeps deterministic mutation gates without template-like
dialogue. Gemma 4 12B remains the configured salon fallback.
It validates the model proposal and invokes only the matching reservation
domain operation. Proposed mutations enter a confirmation state. A later,
explicit affirmative response atomically updates the file and emits both
`salon.reservation.updated` and `salon.owner.notification`. A rejection clears
the proposal without writing. `salon.call.end` closes the simulated call.

The model may propose only `respond`, `availability`, `book`, `modify`, or
`cancel`. It cannot write files or supply a command. Invalid schemas, unknown
service/staff identifiers, and verbatim caller echoes fail closed. Actual
availability and mutation results are returned to Gemma for natural narration;
the model cannot alter the result. The domain service remains the source of
truth for:

- past dates and the 90-day booking horizon;
- closed days, business hours, and 30-minute slot alignment;
- service duration and staff qualification;
- overlapping bookings, duplicate phone/time bookings, and staff selection;
- reservation-code and phone verification for changes and cancellation.

The harness keeps recent dialogue as bounded context while making the latest
caller utterance the only active user turn. It rejects replies that expose
internal action/slot markers or closely repeat a recent assistant response,
then allows one bounded model retry. This varies refusals without replacing
model-authored conversation with code-authored templates.

## Storage and recovery

| Purpose | Windows path | WSL path |
|---|---|---|
| Active reservation table | `E:\Data\LocalVoiceAgent\salon\reservations.json` | `/mnt/e/Data/LocalVoiceAgent/salon/reservations.json` |
| Local fast-recovery copies | `D:\LocalBackup\LocalVoiceAgent\salon\<timestamp>` | `/mnt/d/LocalBackup/LocalVoiceAgent/salon/<timestamp>` |
| Web QA reservation table | `E:\Data\LocalVoiceAgent\salon\qa-reservations.json` | `/mnt/e/Data/LocalVoiceAgent/salon/qa-reservations.json` |
| Web QA recovery copies | `D:\LocalBackup\LocalVoiceAgent\salon-qa\<timestamp>` | `/mnt/d/LocalBackup/LocalVoiceAgent/salon-qa/<timestamp>` |
| Policy | `C:\Dev\Repos\local-voice-agent\configs\salon-booking.json` | `/mnt/c/Dev/Repos/local-voice-agent/configs/salon-booking.json` |

The active table is a versioned JSON document written through same-directory
atomic replacement. Before every mutation, the store writes an append-only
timestamped copy and a recovery manifest containing the recoverable time,
source path, size, and SHA-256 digest. Existing backup containers are never
overwritten or automatically pruned.

The `web-qa` launcher never points at the active table by default. It seeds an
empty file named exactly `qa-reservations.json` with three reproducible,
fictitious, domain-validated reservations covering cut, color, and perm. A
non-empty QA table is left unchanged. The seed fails closed if enabled for any
other filename, so browser testing cannot populate the active reservation
table accidentally.

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

## Model harness and optional TTS adapter

`LVA_SALON_LLM_ENABLED=1` enables the authenticated, loopback-only Gemma
conversation harness. On 2026-07-25 the revised harness passed six live
persona/scope/action cases without echoing the caller. Measured response times
were 1,109–1,468 ms. A browser regression using the previously failing
sequence, “다음주 수요일 예약하고 싶어서요” → “뭐가 있어요?” → “너 누구야?”,
produced three contextual persona responses instead of repeating the missing
field prompt. Evidence is stored outside Git at
`E:\Data\LocalVoiceAgent\runtime\evidence\salon-harness-live-20260725T1137.json`.

`LVA_SALON_TTS_ENABLED=1` attaches the existing Qwen3-TTS worker to each
completed salon text response. The interactive stack defaults to the 1.7B
Base checkpoint because the 0.6B checkpoint failed content round-trip checks
for newly imported reference voices. The 0.6B checkpoint remains an explicit
latency-comparison option only. Startup performs one selected-profile synthesis
without retaining its PCM before the stack is reported ready, so the first
accepted call does not pay lazy decoder and prompt-cache initialization.
One assistant response is synthesized as one unit to avoid sentence-boundary
voice changes. The gateway applies a 24 ms release and a 200 ms final pause,
then emits the existing ordered `audio.output.*` events. A TTS failure does
not invalidate a successful text or reservation result.

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
