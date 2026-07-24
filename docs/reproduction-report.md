# Reproduction report

Status: `PASSED`

On 2026-07-24, public revision
`734405e09980d970179881860ad8107ca743d2c7` was cloned into the explicitly
temporary source root
`C:\Dev\Current\local-voice-agent-repro-20260724`.

The clean source tree passed:

- documented prerequisite discovery;
- all 10 repository validators;
- 25 Windows root/script tests;
- Android `clean`, `testDebugUnitTest`, `lintDebug`, `assembleDebug`, and
  `assembleRelease` from an empty Gradle cache;
- 15 Android unit tests with zero failures;
- Android lint with zero findings;
- debug APK v2 signature verification and expected unsigned release state.

The new debug and release APKs were byte-identical to the recorded 0.6.2
artifacts:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Debug | 12,740,262 | `54d470af44b8682ef7788324641d14b779a60754479b3635b2ae37d00aff88e1` |
| Unsigned release | 9,070,865 | `30c28fa866cf0c4ce4c038041f3b6578fca13932f93b95b1731a1f3619a2eb33` |

The reproduction intentionally reused the documented workstation JDK,
Android SDK, and canonical hash-validated external model/runtime stores. It
did not duplicate or redownload models larger than 5 GB. The empty Gradle
cache grew to 1,409,905,248 bytes.

External evidence:
`E:\Data\LocalVoiceAgent\runtime\evidence\reproduction\clean-clone-734405e.json`,
SHA-256
`2e7bbf0a537afb5b3965593a555c7e49048e008f033b3c9e90d4c7d6f39f15d4`.
