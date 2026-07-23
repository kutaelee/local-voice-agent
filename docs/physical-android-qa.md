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
  E:\Data\LocalVoiceAgent\artifacts\android\0.6.2-api37\local-voice-agent-0.6.2-debug.apk `
  -Algorithm SHA256
```

Expected SHA-256:
`54d470af44b8682ef7788324641d14b779a60754479b3635b2ae37d00aff88e1`.

## Install and pair

```powershell
C:\Dev\SDK\Android\platform-tools\adb.exe devices -l
C:\Dev\SDK\Android\platform-tools\adb.exe -s <physical-serial> install -r `
  E:\Data\LocalVoiceAgent\artifacts\android\0.6.2-api37\local-voice-agent-0.6.2-debug.apk
```

Enter the `wss://` private address and pairing token on the device. Do not
paste the token into a shell, screenshot, bug report, or Git file. Confirm
that the app reports `CONNECTED` and that a deliberately wrong token is
rejected without creating a session.

## Required device cases

| Case | Pass condition |
|---|---|
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
