package dev.localvoiceagent.android.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.localvoiceagent.android.network.GatewayConnectionState
import dev.localvoiceagent.android.network.GatewayEvent
import dev.localvoiceagent.android.network.PcGatewayClient
import dev.localvoiceagent.android.network.ServerEndpoint
import dev.localvoiceagent.android.protocol.ProtocolEnvelope
import dev.localvoiceagent.android.security.PairingTokenStore
import java.util.UUID
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val tokenStore = PairingTokenStore(application)
    private val gateway = PcGatewayClient(viewModelScope)
    private val mutableState = MutableStateFlow(
        AppUiState(
            serverUrl = tokenStore.serverUrl().orEmpty(),
            pairingConfigured = tokenStore.hasToken() && tokenStore.serverUrl() != null,
        ),
    )

    val state: StateFlow<AppUiState> = mutableState.asStateFlow()

    init {
        viewModelScope.launch {
            gateway.events.collect(::handleGatewayEvent)
        }
    }

    fun dispatch(action: AppAction) {
        when (action) {
            is AppAction.SavePairing -> savePairing(action)
            AppAction.Connect -> connect()
            AppAction.Disconnect -> gateway.disconnect()
            AppAction.Interrupt -> interrupt()
            is AppAction.ApprovalDecision -> respondToApproval(action.approved)
            else -> reduce(action)
        }
    }

    override fun onCleared() {
        gateway.disconnect()
    }

    private fun savePairing(action: AppAction.SavePairing) {
        val endpoint = runCatching { ServerEndpoint.parse(action.serverUrl) }
            .getOrElse {
                reduce(AppAction.ReportError(it.message ?: "Server URL is invalid"))
                return
            }
        runCatching { tokenStore.save(endpoint.baseUrl, action.token) }
            .onSuccess {
                reduce(action.copy(serverUrl = endpoint.baseUrl))
            }
            .onFailure {
                reduce(AppAction.ReportError("Pairing settings could not be stored"))
            }
    }

    private fun connect() {
        val token = tokenStore.load()
        val serverUrl = tokenStore.serverUrl()
        if (token == null || serverUrl == null) {
            reduce(AppAction.ReportError("Pairing is not configured"))
            return
        }
        reduce(AppAction.Connect)
        runCatching { gateway.connect(serverUrl, token) }
            .onFailure {
                reduce(AppAction.ReportError(it.message ?: "Connection could not start"))
            }
    }

    private fun interrupt() {
        val targetId = mutableState.value.activeRequestId
        if (targetId != null) {
            val sent = runCatching {
                gateway.send(
                    type = "operation.cancel.requested",
                    payload = buildJsonObject {
                        put("target_kind", "assistant_response")
                        put("target_id", UUID.fromString(targetId).toString())
                        put("reason", "barge_in")
                        put("idempotency_key", UUID.randomUUID().toString())
                    },
                )
            }.getOrDefault(false)
            if (!sent) {
                reduce(AppAction.ReportError("Interrupt request could not be sent"))
                return
            }
        }
        reduce(AppAction.Interrupt)
    }

    private fun respondToApproval(approved: Boolean) {
        val approval = mutableState.value.pendingApproval ?: return
        val sent = gateway.send(
            type = "tool.approval.response",
            payload = buildJsonObject {
                put("approval_id", approval.approvalId)
                put("decision", if (approved) "approve" else "reject")
                put("arguments_digest", approval.argumentsDigest)
            },
        )
        if (sent) {
            reduce(AppAction.ApprovalDecision(approved))
        } else {
            reduce(AppAction.ReportError("Approval response could not be sent"))
        }
    }

    private fun handleGatewayEvent(event: GatewayEvent) {
        when (event) {
            is GatewayEvent.ConnectionChanged -> reduce(
                AppAction.SetConnectionState(
                    when (event.state) {
                        GatewayConnectionState.DISCONNECTED -> ConnectionState.DISCONNECTED
                        GatewayConnectionState.CONNECTING -> ConnectionState.CONNECTING
                        GatewayConnectionState.CONNECTED -> ConnectionState.CONNECTED
                        GatewayConnectionState.RECONNECTING -> ConnectionState.RECONNECTING
                    },
                ),
            )
            is GatewayEvent.Failure -> reduce(
                AppAction.ReportError(
                    when (event.code) {
                        "PAIRING_REJECTED" -> "Pairing token was rejected"
                        "PROTOCOL_INVALID", "PROTOCOL_REPLAY" -> "Server protocol validation failed"
                        else -> if (event.retrying) {
                            "Connection failed; retrying"
                        } else {
                            "Connection failed"
                        }
                    },
                ),
            )
            is GatewayEvent.Message -> handleEnvelope(event.envelope)
        }
    }

    private fun handleEnvelope(envelope: ProtocolEnvelope) {
        runCatching {
            when (envelope.type) {
                "assistant.state" -> reduce(
                    AppAction.SetAssistantState(
                        assistantState(
                            envelope.payload.getValue("state").jsonPrimitive.content,
                        ),
                    ),
                )
                "transcript.user.partial", "transcript.user.final" -> reduce(
                    AppAction.SetUserTranscript(
                        envelope.payload.getValue("text").jsonPrimitive.content,
                    ),
                )
                "assistant.text.delta" -> reduce(
                    AppAction.AppendAssistantText(
                        requestId = envelope.requestId.toString(),
                        sequence = envelope.sequence,
                        text = envelope.payload.getValue("text").jsonPrimitive.content,
                    ),
                )
                "assistant.text.final" -> reduce(
                    AppAction.SetAssistantText(
                        requestId = envelope.requestId.toString(),
                        sequence = envelope.sequence,
                        text = envelope.payload.getValue("text").jsonPrimitive.content,
                    ),
                )
                "tool.approval.required" -> reduce(
                    AppAction.SetPendingApproval(
                        requestId = envelope.requestId.toString(),
                        sequence = envelope.sequence,
                        approval = PendingApproval(
                            approvalId = envelope.payload.getValue("approval_id")
                                .jsonPrimitive.content,
                            toolName = envelope.payload.getValue("tool_name")
                                .jsonPrimitive.content,
                            riskLevel = envelope.payload.getValue("risk_level")
                                .jsonPrimitive.int,
                            target = envelope.payload.getValue("target").jsonPrimitive.content,
                            argumentsDigest = envelope.payload.getValue("arguments_digest")
                                .jsonPrimitive.content,
                            expectedChanges = envelope.payload.getValue("expected_changes")
                                .jsonPrimitive.content,
                            impactScope = envelope.payload.getValue("impact_scope")
                                .jsonPrimitive.content,
                            rollback = envelope.payload.getValue("rollback")
                                .jsonPrimitive.content,
                        ),
                    ),
                )
                "tool.started", "tool.progress", "tool.completed", "tool.failed",
                "tool.rollback.started", "tool.rollback.completed",
                -> reduce(
                    AppAction.SetExecutionSummary(
                        sequence = envelope.sequence,
                        summary = "${envelope.type}: " +
                            (envelope.payload["message"]?.jsonPrimitive?.contentOrNull
                                ?: envelope.payload["status"]?.jsonPrimitive?.contentOrNull
                                ?: "updated"),
                    ),
                )
                "model.switch.started" -> reduce(
                    AppAction.SetAssistantState(AssistantState.SWITCHING_MODEL),
                )
                "model.switch.completed" -> reduce(
                    AppAction.SetAssistantState(AssistantState.THINKING),
                )
                "error" -> reduce(
                    AppAction.ReportError(
                        envelope.payload["message"]?.jsonPrimitive?.contentOrNull
                            ?: "Server reported an error",
                    ),
                )
            }
        }.onFailure {
            reduce(AppAction.ReportError("Server payload validation failed"))
        }
    }

    private fun assistantState(value: String): AssistantState = when (value) {
        "listening" -> AssistantState.LISTENING
        "recognizing" -> AssistantState.RECOGNIZING
        "thinking" -> AssistantState.THINKING
        "selecting_tool" -> AssistantState.SELECTING_TOOL
        "waiting_approval" -> AssistantState.WAITING_APPROVAL
        "executing" -> AssistantState.EXECUTING
        "verifying" -> AssistantState.VERIFYING
        "synthesizing" -> AssistantState.SYNTHESIZING
        "speaking" -> AssistantState.SPEAKING
        "interrupted" -> AssistantState.INTERRUPTED
        "switching_model" -> AssistantState.SWITCHING_MODEL
        else -> AssistantState.IDLE
    }

    private fun reduce(action: AppAction) {
        mutableState.value = AppReducer.reduce(mutableState.value, action)
    }
}
