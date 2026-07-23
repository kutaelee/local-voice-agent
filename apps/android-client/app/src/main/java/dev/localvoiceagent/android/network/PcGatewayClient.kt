package dev.localvoiceagent.android.network

import dev.localvoiceagent.android.protocol.ProtocolEnvelope
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

enum class GatewayConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
    RECONNECTING,
}

sealed interface GatewayEvent {
    data class ConnectionChanged(val state: GatewayConnectionState) : GatewayEvent
    data class Message(val envelope: ProtocolEnvelope) : GatewayEvent
    data class Failure(val code: String, val retrying: Boolean) : GatewayEvent
}

class PcGatewayClient(
    private val scope: CoroutineScope,
    private val httpClient: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .connectTimeout(10, TimeUnit.SECONDS)
        .build(),
    private val socketFactory: (
        (Request, WebSocketListener) -> WebSocket
    )? = null,
    private val reconnectDelayProvider: (Int) -> Long = { attempt ->
        (1_000L shl attempt.coerceAtMost(5)).coerceAtMost(30_000L)
    },
) {
    private val mutableEvents = MutableSharedFlow<GatewayEvent>(
        extraBufferCapacity = 64,
    )
    val events: SharedFlow<GatewayEvent> = mutableEvents.asSharedFlow()

    private var socket: WebSocket? = null
    private var endpoint: ServerEndpoint? = null
    private var pairingToken: String? = null
    private var sessionId: UUID? = null
    private val clientSequence = AtomicInteger(0)
    private var serverSequence = -1
    private var reconnectAttempt = 0
    private var reconnectJob: Job? = null
    private var userClosed = true
    private var generation = 0

    fun connect(serverUrl: String, token: String) {
        require(token.length in 32..4096) { "Pairing token length is invalid" }
        disconnect()
        generation += 1
        endpoint = ServerEndpoint.parse(serverUrl)
        pairingToken = token
        sessionId = UUID.randomUUID()
        clientSequence.set(0)
        serverSequence = -1
        reconnectAttempt = 0
        userClosed = false
        openSocket(reconnecting = false)
    }

    fun disconnect() {
        userClosed = true
        generation += 1
        reconnectJob?.cancel()
        reconnectJob = null
        socket?.close(1000, "client disconnect")
        socket = null
        pairingToken = null
        endpoint = null
        sessionId = null
        mutableEvents.tryEmit(
            GatewayEvent.ConnectionChanged(GatewayConnectionState.DISCONNECTED),
        )
    }

    fun send(type: String, payload: JsonObject, requestId: UUID = UUID.randomUUID()): Boolean {
        val activeSession = sessionId ?: return false
        val envelope = ProtocolEnvelope.createClient(
            type = type,
            sessionId = activeSession,
            requestId = requestId,
            sequence = clientSequence.getAndIncrement(),
            payload = payload,
        )
        return socket?.send(envelope.encode()) == true
    }

    private fun openSocket(reconnecting: Boolean) {
        val activeEndpoint = endpoint ?: return
        val activeToken = pairingToken ?: return
        val activeSession = sessionId ?: return
        val activeGeneration = generation
        mutableEvents.tryEmit(
            GatewayEvent.ConnectionChanged(
                if (reconnecting) {
                    GatewayConnectionState.RECONNECTING
                } else {
                    GatewayConnectionState.CONNECTING
                },
            ),
        )
        val request = Request.Builder()
            .url(
                activeEndpoint.sessionEventsUrl(
                    activeSession.toString(),
                    afterSequence = if (reconnecting) serverSequence else null,
                ),
            )
            .header("Authorization", "Bearer $activeToken")
            .build()
        val listener = Listener(activeSession, activeGeneration)
        socket = socketFactory?.invoke(request, listener)
            ?: httpClient.newWebSocket(request, listener)
    }

    private fun scheduleReconnect() {
        if (userClosed || reconnectJob?.isActive == true) return
        val delayMillis = reconnectDelayProvider(reconnectAttempt)
        require(delayMillis in 0..30_000) {
            "Reconnect delay is outside the safety range"
        }
        reconnectAttempt += 1
        reconnectJob = scope.launch {
            mutableEvents.emit(
                GatewayEvent.ConnectionChanged(GatewayConnectionState.RECONNECTING),
            )
            delay(delayMillis)
            if (!userClosed) openSocket(reconnecting = true)
        }
    }

    private inner class Listener(
        private val expectedSessionId: UUID,
        private val expectedGeneration: Int,
    ) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (expectedGeneration != generation) {
                webSocket.close(1000, "superseded connection")
                return
            }
            reconnectAttempt = 0
            reconnectJob?.cancel()
            reconnectJob = null
            mutableEvents.tryEmit(
                GatewayEvent.ConnectionChanged(GatewayConnectionState.CONNECTED),
            )
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (expectedGeneration != generation) return
            val envelope = runCatching { ProtocolEnvelope.parse(text) }
                .getOrElse {
                    mutableEvents.tryEmit(
                        GatewayEvent.Failure("PROTOCOL_INVALID", retrying = false),
                    )
                    webSocket.close(1002, "invalid protocol envelope")
                    return
                }
            if (envelope.sessionId != expectedSessionId || envelope.sequence <= serverSequence) {
                mutableEvents.tryEmit(
                    GatewayEvent.Failure("PROTOCOL_REPLAY", retrying = false),
                )
                webSocket.close(1002, "invalid session or sequence")
                return
            }
            serverSequence = envelope.sequence
            mutableEvents.tryEmit(GatewayEvent.Message(envelope))
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            if (expectedGeneration != generation) return
            webSocket.close(code, reason)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            if (expectedGeneration != generation) return
            if (userClosed) return
            val terminalFailure = when (code) {
                4400 -> "PROTOCOL_INVALID"
                4401 -> "PAIRING_REJECTED"
                4409 -> "SESSION_CONFLICT"
                4410 -> "SESSION_RESUME_EXPIRED"
                else -> null
            }
            if (terminalFailure == null) {
                scheduleReconnect()
                return
            }
            userClosed = true
            mutableEvents.tryEmit(
                GatewayEvent.Failure(
                    code = terminalFailure,
                    retrying = false,
                ),
            )
            mutableEvents.tryEmit(
                GatewayEvent.ConnectionChanged(
                    GatewayConnectionState.DISCONNECTED,
                ),
            )
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            if (expectedGeneration != generation) return
            if (userClosed) return
            val authenticationFailed = response?.code in setOf(401, 403)
            mutableEvents.tryEmit(
                GatewayEvent.Failure(
                    code = if (authenticationFailed) "PAIRING_REJECTED" else "CONNECTION_FAILED",
                    retrying = !authenticationFailed,
                ),
            )
            if (authenticationFailed) {
                userClosed = true
            } else {
                scheduleReconnect()
            }
        }
    }
}
