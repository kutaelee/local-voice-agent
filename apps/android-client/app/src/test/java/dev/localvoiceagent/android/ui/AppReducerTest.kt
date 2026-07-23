package dev.localvoiceagent.android.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AppReducerTest {
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
            AppAction.SavePairing("https://pc.example", "x".repeat(32)),
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
            pendingApproval = "delete file",
        )
        val denied = AppReducer.reduce(
            waiting,
            AppAction.ApprovalDecision(approved = false),
        )

        assertFalse(denied.assistantState == AssistantState.EXECUTING)
        assertNull(denied.pendingApproval)
    }
}
