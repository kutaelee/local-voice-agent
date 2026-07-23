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

Version 0.4.1 was installed on an API 37 emulator. Version 0.4.2 adds the
private-CA network configuration. Version 0.5.0 persists an unresolved
approval and bounded execution summaries through Room, without retaining raw
audio or transcript text. Version 0.6.0 requests Bluetooth-connect permission
with microphone capture and selects an available modern communication device
for the foreground voice session. Launch, status/navigation
insets, the More destination list, portrait/landscape recreation, and
force-stop/relaunch passed without an AndroidRuntime error. Physical-device
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
