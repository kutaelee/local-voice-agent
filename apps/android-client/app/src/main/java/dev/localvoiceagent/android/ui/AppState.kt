package dev.localvoiceagent.android.ui

enum class AppDestination(val label: String) {
    PAIRING("Pairing"),
    VOICE("Voice"),
    HISTORY("History"),
    APPROVAL("Approval"),
    EXECUTION("Execution"),
    EVIDENCE("Evidence"),
    DIAGNOSTICS("Diagnostics"),
    SETTINGS("Settings"),
}

enum class ConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
    RECONNECTING,
    ERROR,
}

enum class AssistantState {
    IDLE,
    LISTENING,
    RECOGNIZING,
    THINKING,
    SELECTING_TOOL,
    WAITING_APPROVAL,
    EXECUTING,
    VERIFYING,
    SYNTHESIZING,
    SPEAKING,
    INTERRUPTED,
    SWITCHING_MODEL,
}

data class PendingApproval(
    val approvalId: String,
    val toolName: String,
    val riskLevel: Int,
    val target: String,
    val argumentsDigest: String,
    val expectedChanges: String,
    val impactScope: String,
    val rollback: String,
)

data class AppUiState(
    val destination: AppDestination = AppDestination.PAIRING,
    val connectionState: ConnectionState = ConnectionState.DISCONNECTED,
    val assistantState: AssistantState = AssistantState.IDLE,
    val serverUrl: String = "",
    val pairingConfigured: Boolean = false,
    val userTranscript: String = "",
    val assistantTranscript: String = "",
    val pendingApproval: PendingApproval? = null,
    val executionSummary: String = "No execution",
    val activeRequestId: String? = null,
    val lastServerSequence: Int = -1,
    val lastError: String? = null,
)

sealed interface AppAction {
    data class Navigate(val destination: AppDestination) : AppAction
    data class SavePairing(val serverUrl: String, val token: String) : AppAction
    data object Connect : AppAction
    data object Disconnect : AppAction
    data object StartListening : AppAction
    data object StopListening : AppAction
    data object Interrupt : AppAction
    data class SetConnectionState(val state: ConnectionState) : AppAction
    data class SetAssistantState(val state: AssistantState) : AppAction
    data class SetUserTranscript(val text: String) : AppAction
    data class AppendAssistantText(
        val requestId: String,
        val sequence: Int,
        val text: String,
    ) : AppAction
    data class SetAssistantText(
        val requestId: String,
        val sequence: Int,
        val text: String,
    ) : AppAction
    data class SetPendingApproval(
        val requestId: String,
        val sequence: Int,
        val approval: PendingApproval,
    ) : AppAction
    data class SetExecutionSummary(val sequence: Int, val summary: String) : AppAction
    data class ApprovalDecision(val approved: Boolean) : AppAction
    data class ReportError(val message: String) : AppAction
}

object AppReducer {
    fun reduce(state: AppUiState, action: AppAction): AppUiState = when (action) {
        is AppAction.Navigate -> state.copy(destination = action.destination)
        is AppAction.SavePairing -> state.copy(
            serverUrl = action.serverUrl.trim(),
            pairingConfigured = action.serverUrl.isNotBlank() && action.token.isNotBlank(),
            lastError = null,
        )
        AppAction.Connect -> if (state.pairingConfigured) {
            state.copy(connectionState = ConnectionState.CONNECTING, lastError = null)
        } else {
            state.copy(lastError = "Pairing is not configured")
        }
        AppAction.Disconnect -> state.copy(
            connectionState = ConnectionState.DISCONNECTED,
            assistantState = AssistantState.IDLE,
        )
        AppAction.StartListening -> state.copy(
            assistantState = AssistantState.LISTENING,
            destination = AppDestination.VOICE,
        )
        AppAction.StopListening -> state.copy(assistantState = AssistantState.RECOGNIZING)
        AppAction.Interrupt -> state.copy(assistantState = AssistantState.INTERRUPTED)
        is AppAction.SetConnectionState -> state.copy(
            connectionState = action.state,
            lastError = if (action.state == ConnectionState.CONNECTED) null else state.lastError,
        )
        is AppAction.SetAssistantState -> state.copy(assistantState = action.state)
        is AppAction.SetUserTranscript -> state.copy(userTranscript = action.text)
        is AppAction.AppendAssistantText -> state.copy(
            assistantTranscript = state.assistantTranscript + action.text,
            activeRequestId = action.requestId,
            lastServerSequence = action.sequence,
        )
        is AppAction.SetAssistantText -> state.copy(
            assistantTranscript = action.text,
            activeRequestId = action.requestId,
            lastServerSequence = action.sequence,
        )
        is AppAction.SetPendingApproval -> state.copy(
            destination = AppDestination.APPROVAL,
            assistantState = AssistantState.WAITING_APPROVAL,
            pendingApproval = action.approval,
            activeRequestId = action.requestId,
            lastServerSequence = action.sequence,
        )
        is AppAction.SetExecutionSummary -> state.copy(
            executionSummary = action.summary,
            lastServerSequence = action.sequence,
        )
        is AppAction.ApprovalDecision -> state.copy(
            assistantState = if (action.approved) {
                AssistantState.EXECUTING
            } else {
                AssistantState.IDLE
            },
            pendingApproval = null,
        )
        is AppAction.ReportError -> state.copy(
            connectionState = ConnectionState.ERROR,
            lastError = action.message,
        )
    }
}
