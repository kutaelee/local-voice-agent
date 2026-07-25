# Reproduction report

Status: `PASSED`

On 2026-07-25, public revision
`961285794b29cdd0a00d83c31833498f770641fc` was cloned into the explicitly
temporary source root
`C:\Dev\Current\local-voice-agent-repro-9612857`.

The clean source tree passed:

- documented Windows installation and model-download plan-only discovery;
- canonical model inventory verification: 17 size-matched files,
  134,139,969,659 bytes, with zero download required;
- all 10 repository validators;
- 28 Windows root/script tests and three Linux private-CA tests;
- Android `clean`, `testDebugUnitTest`, `lintDebug`, `assembleDebug`, and
  `assembleRelease` from an empty Gradle cache;
- 30 Android unit tests with zero failures;
- Android lint with zero findings;
- debug APK v2 signature verification and expected unsigned release state.

The clean-clone APKs were byte-identical to a second clean build in the
canonical repository and to the corrected public 0.6.9 release assets:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Debug | 12,822,182 | `bd81dc7463e75ea1d71abf1410c862ada6d5b66c5817867409dae0ffbe2a40c7` |
| Unsigned release | 9,120,013 | `921ff6c7b9b45fb905db31f3427b68139a22fc44227346624d41618240ba1ab2` |

The reproduction intentionally reused the documented workstation JDK,
Android SDK, and canonical hash-validated external model/runtime stores. It
did not duplicate or redownload models larger than 5 GB. The empty Gradle
cache grew to 1,411,330,000 bytes.

The first published 0.6.9 debug APK was an incremental-build artifact. It had
zero downloads when detected, was preserved outside Git under the
`superseded` artifact directory, and the public asset was replaced with the
clean, independently reproduced APK above. The unsigned release APK already
matched and was not replaced.

External evidence:
`E:\Data\LocalVoiceAgent\runtime\evidence\reproduction\clean-clone-9612857.json`,
SHA-256
`540c7d8a5fa35c98d3111779ac32222bc967b6dcde1bb11b561231dfd2ac3a9d`.
