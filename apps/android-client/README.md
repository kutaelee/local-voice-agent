# Android client

Native Kotlin and Jetpack Compose client using ViewModel, `StateFlow`,
immutable `UiState`, and one-way event flow. Pairing tokens are encrypted with
an Android Keystore-backed AES key before they enter private app preferences.
Only `wss://` server origins are accepted. Cleartext is disabled. The release
candidate trusts only platform system CAs; the debug APK additionally accepts a
device-owner-installed private CA for an explicitly configured private-LAN
server.

The client contains all eight required destinations, connection/assistant
states, Keystore pairing, authenticated TLS WebSocket transport, PCM capture
and playback, approval controls, interruption, reconnect handling, and a
microphone foreground-service boundary. Four primary destinations fit the
bottom bar; History, Execution, Evidence, and Settings remain reachable from
More without clipping compact screens.

Version 0.4.1 was first installed on an API 37 emulator and exposed two layout
issues that were corrected. Version 0.4.2 adds the private-CA network
configuration. Version 0.5.0 persists an unresolved
approval and bounded execution summaries through Room, without retaining raw
audio or transcript text. Version 0.6.0 requests Bluetooth-connect permission
with microphone capture and selects an available modern communication device
for the foreground voice session. Version 0.6.1 separates normal playback
drain from interruption: barge-in immediately flushes the active track and
invalidates all queued chunks from the prior response generation. Version
0.6.4 starts one continuous call after Connect: server VAD ends each user
turn, completed playback automatically starts the next listening turn, and
the user can pause with End call or force the current turn with Send now.
Interrupt no longer reports an expected stale `AudioTrack.write` result as a
playback failure. It also resumes a disconnected session from the last
accepted server sequence
and stops automatic retries when the bounded replay window has expired.
Version 0.6.5 adds an authenticated Settings → Voice catalog, explicit
rights/local-processing consent before reference-WAV upload, server-side
profile selection, Chatterbox expression/CFG/temperature controls, and
pitch-preserving Android playback speed from 0.85× to 1.25×. Reference audio
is stored only under the paired PC's external application-data root and never
inside the repository or APK. Version 0.6.6 switches the production voice
worker to Qwen3-TTS 1.7B Base. Reference upload now requires the exact spoken
transcript and a neutral, happy, dark, or advert tone. The transcript remains
on the paired PC and is not returned by the profile API. Comma-based early
splitting was removed to avoid audible mid-phrase joins; synthesis starts at
completed sentence boundaries and the worker adds a measured 160 ms terminal
tail.
The previous 0.6.2 debug APK was installed on an API 36 x86_64 emulator and
passed cold
launch, all primary destinations, portrait/landscape recreation, and
force-stop/relaunch without a crash-buffer entry. Physical-device
private-CA installation, microphone, Bluetooth, Room process-recovery on a
physical device, and end-to-end voice timing remain separate acceptance tests.

## Isolated build

The workstation SDK is installed under `C:\Dev\SDK\Android`; the repository
does not depend on a system PATH change.

```powershell
$env:JAVA_HOME = 'C:\Dev\Java\jdk17'
$env:ANDROID_HOME = 'C:\Dev\SDK\Android'
$env:GRADLE_USER_HOME = 'E:\Cache\LocalVoiceAgent\gradle'
.\gradlew.bat --no-daemon --non-interactive `
  testDebugUnitTest lintDebug assembleDebug assembleRelease
```

The tested toolchain is Android API 37, Build Tools 36.0.0, AGP 9.3.0,
Gradle 9.6.1, JDK 17, and Compose BOM 2026.06.00. Generated APKs remain under
`app\build\outputs\apk`; verified copies and hashes are listed in
`manifests/android-artifacts.yaml`. Signing keys, pairing tokens,
`local.properties`, Gradle caches, and APKs are excluded from Git.
