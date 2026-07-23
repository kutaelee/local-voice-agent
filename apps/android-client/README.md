# Android client

Kotlin + Jetpack Compose client using ViewModel, `StateFlow`, immutable
`UiState`, and one-way event flow. Room is limited to recent conversation and
pending-request cache; pairing secrets belong in Android Keystore.

The app connects only to the PC API gateway. It never contacts the tool
executor or model runtime directly. Audio uses interruptible half-duplex:
microphone monitoring continues during playback, barge-in stops TTS and
discards buffered output, then the client sends the new utterance and
interruption state.

Android Studio, SDK, Gradle, and APK setup remain blocked until the missing
system tools are reviewed under the workstation approval rules.
