# Android client

Native Kotlin and Jetpack Compose client using ViewModel, `StateFlow`,
immutable `UiState`, and one-way event flow. Pairing tokens are encrypted with
an Android Keystore-backed AES key before they enter private app preferences.

The current Slice 8 scaffold contains the eight required navigation
destinations, connection/assistant states, pairing input, approval controls,
diagnostics placeholders, and a microphone foreground-service boundary. It
does not yet claim WebSocket, audio streaming, Bluetooth, Room persistence,
or device-test completion.

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
