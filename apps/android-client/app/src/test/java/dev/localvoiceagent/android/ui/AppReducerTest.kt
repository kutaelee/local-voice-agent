package dev.localvoiceagent.android.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AppReducerTest {
    @Test
    fun connectedPairingNavigatesToVoiceScreen() {
        val pairing = AppUiState(
            destination = AppDestination.PAIRING,
            connectionState = ConnectionState.CONNECTING,
            pairingConfigured = true,
        )

        val connected = AppReducer.reduce(
            pairing,
            AppAction.SetConnectionState(ConnectionState.CONNECTED),
        )

        assertEquals(ConnectionState.CONNECTED, connected.connectionState)
        assertEquals(AppDestination.VOICE, connected.destination)
    }

    @Test
    fun connectStartsContinuousConversationIntent() {
        val paired = AppUiState(pairingConfigured = true)

        val connecting = AppReducer.reduce(paired, AppAction.Connect)

        assertTrue(connecting.conversationActive)
    }

    @Test
    fun ordinaryVoiceErrorDoesNotCorruptTransportState() {
        val connected = AppUiState(
            connectionState = ConnectionState.CONNECTED,
            conversationActive = true,
        )

        val reported = AppReducer.reduce(
            connected,
            AppAction.ReportError("Audio playback write failed"),
        )

        assertEquals(ConnectionState.CONNECTED, reported.connectionState)
        assertEquals("Audio playback write failed", reported.lastError)
    }

    @Test
    fun endConversationStopsAutomaticTurnLoop() {
        val active = AppUiState(
            connectionState = ConnectionState.CONNECTED,
            conversationActive = true,
            assistantState = AssistantState.LISTENING,
        )

        val ended = AppReducer.reduce(active, AppAction.EndConversation)

        assertFalse(ended.conversationActive)
        assertEquals(AssistantState.IDLE, ended.assistantState)
    }

    @Test
    fun connectFailsClosedWithoutPairing() {
        val result = AppReducer.reduce(AppUiState(), AppAction.Connect)

        assertEquals(ConnectionState.DISCONNECTED, result.connectionState)
        assertEquals("Pairing is not configured", result.lastError)
    }

    @Test
    fun validPairingAllowsConnectionAttempt() {
        val paired = AppReducer.reduce(
            AppUiState(),
            AppAction.SavePairing("wss://pc.example", "x".repeat(32)),
        )
        val connecting = AppReducer.reduce(paired, AppAction.Connect)

        assertTrue(paired.pairingConfigured)
        assertEquals(ConnectionState.CONNECTING, connecting.connectionState)
        assertNull(connecting.lastError)
    }

    @Test
    fun interruptMovesAssistantToExplicitTerminalState() {
        val speaking = AppUiState(assistantState = AssistantState.SPEAKING)
        val interrupted = AppReducer.reduce(speaking, AppAction.Interrupt)

        assertEquals(AssistantState.INTERRUPTED, interrupted.assistantState)
    }

    @Test
    fun denialClearsPendingApprovalWithoutExecuting() {
        val waiting = AppUiState(
            assistantState = AssistantState.WAITING_APPROVAL,
            pendingApproval = PendingApproval(
                approvalId = "a",
                toolName = "delete_file",
                riskLevel = 2,
                target = "file.txt",
                argumentsDigest = "a".repeat(64),
                expectedChanges = "delete one file",
                impactScope = "workspace",
                rollback = "restore backup",
            ),
        )
        val denied = AppReducer.reduce(
            waiting,
            AppAction.ApprovalDecision(approved = false),
        )

        assertFalse(denied.assistantState == AssistantState.EXECUTING)
        assertNull(denied.pendingApproval)
    }

    @Test
    fun voiceCatalogUpdatesSelectedProfileAndControls() {
        val profile = VoiceProfileOption(
            profileId = "profile-id",
            name = "Korean reference",
            isDefault = false,
            durationMs = 8_192,
        )

        val updated = AppReducer.reduce(
            AppUiState(voiceSettingsBusy = true),
            AppAction.SetVoiceCatalog(
                profiles = listOf(profile),
                selectedProfileId = profile.profileId,
                playbackRate = 1.1f,
                exaggeration = 0.5f,
                cfgWeight = 0.5f,
                temperature = 0.8f,
            ),
        )

        assertEquals(profile.profileId, updated.selectedVoiceProfileId)
        assertEquals(1.1f, updated.voicePlaybackRate)
        assertFalse(updated.voiceSettingsBusy)
    }

    @Test
    fun voiceControlsAreClampedToSupportedRanges() {
        val tooFast = AppReducer.reduce(
            AppUiState(),
            AppAction.SetVoicePlaybackRate(2.0f),
        )
        val tooExpressive = AppReducer.reduce(
            tooFast,
            AppAction.SetVoiceExaggeration(2.0f),
        )

        assertEquals(1.25f, tooExpressive.voicePlaybackRate)
        assertEquals(1.0f, tooExpressive.voiceExaggeration)
    }
}
