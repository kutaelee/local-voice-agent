# Physical Android QA

Status: `NOT_RUN`

This checklist closes the device-only portions of acceptance criteria 7 and
8. It does not require a public port, Android Studio, raw-audio retention, or
placing a pairing token in a command line or evidence file.

## Preconditions

1. Use a physical Android 8+ device with USB debugging temporarily enabled.
2. Connect the PC and phone through the same trusted LAN or an approved
   private VPN. Do not configure router port forwarding.
3. Start the PC server with its private-LAN TLS profile and install only the
   generated public root CA certificate on the test device. Never copy the CA
   private key to Android.
4. Confirm the APK before installation:

```powershell
Get-FileHash `
  E:\Data\LocalVoiceAgent\artifacts\android\0.6.6-api37\local-voice-agent-0.6.6-debug.apk `
  -Algorithm SHA256
```

Expected SHA-256:
`7ae623d3259d6f86ba612b4ee6b098118661254403c660a6633fa220321e8066`.

## Install and pair

Run the read-only preflight first. It rejects emulators, requires exactly one
authorized physical device, and verifies the recorded APK hash:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\physical-android-qa.ps1 -Action preflight
```

The verified installer is explicit and never accepts a pairing token:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\physical-android-qa.ps1 `
  -Action install -DeviceSerial <physical-serial>
```

Enter the `wss://` private address and pairing token on the device. Do not
paste the token into a shell, screenshot, bug report, or Git file. Confirm
that the app reports `CONNECTED` and that a deliberately wrong token is
rejected without creating a session.

## Required device cases

| Case | Pass condition |
|---|---|
| Invalid pairing token | A wrong token is rejected without creating a usable session. |
| Microphone permission | First-use prompt appears; denial is recoverable; grant enables capture. |
| 20 sequential turns | Twenty Korean voice turns complete without process restart or stale audio. |
| Speaker | Assistant audio is ordered and intelligible through the speaker route. |
| Earpiece | Communication route changes without losing the WebSocket session. |
| Bluetooth | Connect/disconnect and route changes do not crash or retain an invalid route. |
| Barge-in | Speak during TTS; playback stops immediately, old queued chunks do not resume, and the new turn completes. |
| Background/foreground | Foreground service remains visible during capture; returning to the app restores state. |
| Rotation | Portrait/landscape recreation retains the active session and pending approval. |
| Network loss | Disable Wi-Fi, restore it, and verify bounded same-session replay without duplicate terminal events. |
| Replay expiry | Stay disconnected past the replay window; the client stops automatic retries and requests a new session. |
| Approval | Level 2 plan shows exact target/arguments/impact/rollback; denial performs no tool action. |
| Server switch | Android displays all model-switch phases and remains connected after 12B returns. |
| Voice profile selection | Settings lists the built-in and registered local profile; selecting and saving the reference profile survives refresh. |
| Voice similarity | With the authorized reference selected, the supplied comparison sentence is recognizably the intended speaker without instability or appended speech. |
| Playback speed | 0.85×, 1.0×, and 1.25× change duration while pitch and intelligibility remain acceptable. |

## Evidence

Record metadata only under
`E:\Data\LocalVoiceAgent\runtime\evidence\android\physical`. Include:

- device model, Android API, app version, test timestamp, and network type;
- pass/fail for each case;
- server request/session identifiers with pairing tokens redacted;
- first-audio and barge-in timing if measured;
- crash-buffer result and relevant bounded error codes.

Do not retain raw microphone audio, full transcripts, pairing tokens, private
keys, contacts, notifications, or unrelated device logs. Remove the debug CA
and disable USB debugging after QA unless the device remains an explicitly
managed development device.

## Evidence collector

After installation, initialize the metadata-only evidence file:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\physical-android-qa.ps1 `
  -Action initialize -DeviceSerial <physical-serial>
```

The command prints the new evidence path. Record each observed case only after
performing it on the device:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\physical-android-qa.ps1 `
  -Action set-case `
  -EvidencePath <printed-evidence-path> `
  -Case barge_in -Outcome passed -MeasuredLatencyMs <measured-ms>
```

Finalize only after all 16 cases have a terminal result:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\physical-android-qa.ps1 `
  -Action finalize `
  -DeviceSerial <physical-serial> `
  -EvidencePath <printed-evidence-path>
```

Finalization rechecks the same device model, API level, installed app version,
case completeness, evidence hash, and privacy fields. It reports `passed`
only if every case passed.
