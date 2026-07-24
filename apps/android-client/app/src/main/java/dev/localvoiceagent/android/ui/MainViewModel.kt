package dev.localvoiceagent.android.ui

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.util.Base64
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.core.content.ContextCompat
import dev.localvoiceagent.android.audio.PcmPlayer
import dev.localvoiceagent.android.audio.PcmRecorder
import dev.localvoiceagent.android.audio.VoiceSessionService
import dev.localvoiceagent.android.network.GatewayConnectionState
import dev.localvoiceagent.android.network.GatewayEvent
import dev.localvoiceagent.android.network.PcGatewayClient
import dev.localvoiceagent.android.network.ServerEndpoint
import dev.localvoiceagent.android.network.VoiceProfileClient
import dev.localvoiceagent.android.network.VoiceSettingsDto
import dev.localvoiceagent.android.protocol.ProtocolEnvelope
import dev.localvoiceagent.android.security.PairingTokenStore
import dev.localvoiceagent.android.storage.LocalStateStore
import java.util.UUID
import java.io.ByteArrayOutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val tokenStore = PairingTokenStore(application)
    private val localState = LocalStateStore.create(application)
    private val gateway = PcGatewayClient(viewModelScope)
    private val voiceProfiles = VoiceProfileClient()
    private val mutableState = MutableStateFlow(
        AppUiState(
            serverUrl = tokenStore.serverUrl().orEmpty(),
            pairingConfigured = tokenStore.hasToken() && tokenStore.serverUrl() != null,
        ),
    )
    private val recorder = PcmRecorder(
        context = application,
        scope = viewModelScope,
        onChunk = ::sendAudioChunk,
        onError = { message ->
            viewModelScope.launch {
                stopListening("client_stop")
                reduce(AppAction.ReportError(message))
            }
        },
    )
    private val player = PcmPlayer(
        context = application,
        scope = viewModelScope,
        onError = { message ->
            viewModelScope.launch {
                reduce(AppAction.ReportError(message))
            }
        },
        onPlaybackComplete = {
            viewModelScope.launch {
                if (
                    mutableState.value.conversationActive &&
                    mutableState.value.connectionState == ConnectionState.CONNECTED
                ) {
                    reduce(AppAction.SetAssistantState(AssistantState.IDLE))
                    startListening()
                }
            }
        },
    )
    @Volatile
    private var inputStreamId: UUID? = null
    private var inputChunkIndex = 0

    val state: StateFlow<AppUiState> = mutableState.asStateFlow()

    init {
        viewModelScope.launch {
            gateway.events.collect(::handleGatewayEvent)
        }
        viewModelScope.launch {
            val restored = localState.restore()
            if (restored.pendingApproval != null && mutableState.value.pendingApproval == null) {
                reduce(
                    AppAction.SetPendingApproval(
                        requestId = restored.pendingRequestId.orEmpty(),
                        sequence = restored.pendingSequence,
                        approval = restored.pendingApproval,
                    ),
                )
            }
            if (restored.latestExecutionSummary != null &&
                mutableState.value.executionSummary == "No execution"
            ) {
                reduce(
                    AppAction.SetExecutionSummary(
                        sequence = restored.latestExecutionSequence,
                        summary = restored.latestExecutionSummary,
                    ),
                )
            }
        }
    }

    fun dispatch(action: AppAction) {
        when (action) {
            is AppAction.SavePairing -> savePairing(action)
            AppAction.Connect -> connect()
            AppAction.Disconnect -> {
                endConversation()
                reduce(AppAction.Disconnect)
                gateway.disconnect()
            }
            AppAction.StartListening -> startListening()
            AppAction.StopListening -> stopListening("client_stop")
            AppAction.StartConversation -> {
                reduce(AppAction.StartConversation)
                startListening()
            }
            AppAction.EndConversation -> endConversation()
            AppAction.Interrupt -> interrupt()
            is AppAction.ApprovalDecision -> respondToApproval(action.approved)
            is AppAction.Navigate -> {
                reduce(action)
                if (action.destination == AppDestination.SETTINGS) {
                    refreshVoiceProfiles()
                }
            }
            AppAction.RefreshVoiceProfiles -> refreshVoiceProfiles()
            is AppAction.RegisterVoiceProfile -> registerVoiceProfile(action)
            AppAction.SaveVoiceSettings -> saveVoiceSettings()
            is AppAction.SetAudioOutputRoute -> {
                player.setOutputRoute(action.route)
                reduce(action)
            }
            else -> reduce(action)
        }
    }

    override fun onCleared() {
        recorder.stop()
        player.close()
        stopVoiceService()
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

    private fun refreshVoiceProfiles() {
        val credentials = voiceCredentials() ?: return
        reduce(AppAction.RefreshVoiceProfiles)
        viewModelScope.launch {
            runCatching {
                voiceProfiles.catalog(credentials.first, credentials.second)
            }.onSuccess(::applyVoiceCatalog)
                .onFailure {
                    reduce(
                        AppAction.SetVoiceSettingsMessage(
                            "Voice settings could not be loaded",
                        ),
                    )
                }
        }
    }

    private fun registerVoiceProfile(action: AppAction.RegisterVoiceProfile) {
        val credentials = voiceCredentials() ?: return
        if (
            action.name.isBlank() ||
            action.referenceText.isBlank() ||
            !action.rightsConfirmed ||
            !action.localProcessingConsent
        ) {
            reduce(
                AppAction.SetVoiceSettingsMessage(
                    "Name, exact transcript, voice rights, and local processing consent are required",
                ),
            )
            return
        }
        reduce(action)
        viewModelScope.launch {
            runCatching {
                val wav = readReferenceWav(action.contentUri)
                val created = voiceProfiles.create(
                    endpoint = credentials.first,
                    token = credentials.second,
                    name = action.name.trim(),
                    wav = wav,
                    rightsConfirmed = action.rightsConfirmed,
                    localProcessingConsent = action.localProcessingConsent,
                    referenceText = action.referenceText,
                    style = action.style,
                )
                voiceProfiles.updateSettings(
                    endpoint = credentials.first,
                    token = credentials.second,
                    settings = currentVoiceSettings(
                        profileId = created.profileId,
                    ),
                )
                voiceProfiles.catalog(credentials.first, credentials.second)
            }.onSuccess {
                applyVoiceCatalog(it)
                reduce(
                    AppAction.SetVoiceSettingsMessage(
                        "Reference voice registered locally",
                    ),
                )
            }.onFailure {
                reduce(
                    AppAction.SetVoiceSettingsMessage(
                        it.message ?: "Reference voice registration failed",
                    ),
                )
            }
        }
    }

    private fun saveVoiceSettings() {
        val credentials = voiceCredentials() ?: return
        val settings = currentVoiceSettings()
        reduce(AppAction.SaveVoiceSettings)
        viewModelScope.launch {
            runCatching {
                voiceProfiles.updateSettings(
                    credentials.first,
                    credentials.second,
                    settings,
                )
            }.onSuccess {
                player.setPlaybackRate(it.playbackRate)
                reduce(AppAction.SetVoiceSettingsBusy(false))
                reduce(AppAction.SetVoiceSettingsMessage("Voice settings saved"))
            }.onFailure {
                reduce(
                    AppAction.SetVoiceSettingsMessage(
                        it.message ?: "Voice settings could not be saved",
                    ),
                )
            }
        }
    }

    private fun currentVoiceSettings(
        profileId: String = mutableState.value.selectedVoiceProfileId,
    ): VoiceSettingsDto = VoiceSettingsDto(
        profileId = profileId,
        playbackRate = mutableState.value.voicePlaybackRate,
        exaggeration = mutableState.value.voiceExaggeration,
        cfgWeight = mutableState.value.voiceCfgWeight,
        temperature = mutableState.value.voiceTemperature,
    )

    private fun applyVoiceCatalog(
        catalog: dev.localvoiceagent.android.network.VoiceProfileCatalog,
    ) {
        player.setPlaybackRate(catalog.settings.playbackRate)
        reduce(
            AppAction.SetVoiceCatalog(
                profiles = catalog.profiles.map {
                    VoiceProfileOption(
                        profileId = it.profileId,
                        name = it.name,
                        isDefault = it.isDefault,
                        durationMs = it.durationMs,
                        style = it.style,
                        hasReferenceText = it.hasReferenceText,
                    )
                },
                selectedProfileId = catalog.settings.profileId,
                playbackRate = catalog.settings.playbackRate,
                exaggeration = catalog.settings.exaggeration,
                cfgWeight = catalog.settings.cfgWeight,
                temperature = catalog.settings.temperature,
            ),
        )
    }

    private fun voiceCredentials(): Pair<ServerEndpoint, String>? {
        val token = tokenStore.load()
        val serverUrl = tokenStore.serverUrl()
        if (token == null || serverUrl == null) {
            reduce(
                AppAction.SetVoiceSettingsMessage(
                    "Pairing is required before changing voice settings",
                ),
            )
            return null
        }
        val endpoint = runCatching { ServerEndpoint.parse(serverUrl) }.getOrNull()
        if (endpoint == null) {
            reduce(AppAction.SetVoiceSettingsMessage("Stored server URL is invalid"))
            return null
        }
        return endpoint to token
    }

    private suspend fun readReferenceWav(contentUri: String): ByteArray =
        withContext(Dispatchers.IO) {
            val uri = Uri.parse(contentUri)
            val resolver = getApplication<Application>().contentResolver
            resolver.openInputStream(uri)?.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(64 * 1024)
                var total = 0
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    total += count
                    require(total <= VoiceProfileClient.MAX_REFERENCE_BYTES) {
                        "Reference WAV is larger than 8 MB"
                    }
                    output.write(buffer, 0, count)
                }
                output.toByteArray().also {
                    require(it.isNotEmpty()) { "Reference WAV is empty" }
                }
            } ?: throw IllegalArgumentException("Reference WAV could not be opened")
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
        player.stop()
        if (recorder.isActive) {
            stopListening("barge_in")
        }
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

    private fun endConversation() {
        val hadInput = inputStreamId != null
        stopListening("disconnect")
        player.stop()
        if (!hadInput && mutableState.value.assistantState in setOf(
                AssistantState.THINKING,
                AssistantState.SELECTING_TOOL,
                AssistantState.EXECUTING,
                AssistantState.VERIFYING,
                AssistantState.SYNTHESIZING,
                AssistantState.SPEAKING,
            )
        ) {
            val targetId = mutableState.value.activeRequestId
            if (targetId != null) {
                gateway.send(
                    type = "operation.cancel.requested",
                    payload = buildJsonObject {
                        put("target_kind", "assistant_response")
                        put("target_id", targetId)
                        put("reason", "user_request")
                        put("idempotency_key", UUID.randomUUID().toString())
                    },
                )
            }
        }
        reduce(AppAction.EndConversation)
    }

    private fun startListening() {
        if (mutableState.value.connectionState != ConnectionState.CONNECTED) {
            reduce(AppAction.ReportError("Connect to the PC before using the microphone"))
            return
        }
        if (recorder.isActive) return
        if (mutableState.value.assistantState == AssistantState.SPEAKING) {
            interrupt()
        } else {
            player.stop()
        }
        val streamId = UUID.randomUUID()
        val sent = gateway.send(
            type = "audio.input.start",
            payload = buildJsonObject {
                put("audio_stream_id", streamId.toString())
                put("encoding", "pcm_s16le")
                put("sample_rate_hz", PcmRecorder.SAMPLE_RATE_HZ)
                put("channels", PcmRecorder.CHANNELS)
            },
        )
        if (!sent) {
            reduce(AppAction.ReportError("Audio stream could not be started"))
            return
        }
        inputStreamId = streamId
        inputChunkIndex = 0
        runCatching {
            ContextCompat.startForegroundService(
                getApplication<Application>(),
                Intent(getApplication<Application>(), VoiceSessionService::class.java),
            )
        }.onFailure {
            inputStreamId = null
            reduce(AppAction.ReportError("Microphone foreground service could not start"))
            return
        }
        if (recorder.start()) {
            reduce(AppAction.StartListening)
        } else {
            stopListening("client_stop")
        }
    }

    private fun sendAudioChunk(data: ByteArray, durationMs: Int) {
        val streamId = inputStreamId ?: return
        val sent = gateway.send(
            type = "audio.input.chunk",
            payload = buildJsonObject {
                put("audio_stream_id", streamId.toString())
                put("chunk_index", inputChunkIndex++)
                put("encoding", "pcm_s16le")
                put("duration_ms", durationMs)
                put("data_base64", Base64.encodeToString(data, Base64.NO_WRAP))
            },
        )
        if (!sent) {
            viewModelScope.launch {
                stopListening("disconnect", sendEvent = false)
                reduce(AppAction.ReportError("Audio stream disconnected"))
            }
        }
    }

    private fun stopListening(reason: String, sendEvent: Boolean = true) {
        recorder.stop()
        val streamId = inputStreamId
        inputStreamId = null
        if (sendEvent && streamId != null) {
            gateway.send(
                type = "audio.input.end",
                payload = buildJsonObject {
                    put("audio_stream_id", streamId.toString())
                    put("reason", reason)
                },
            )
        }
        stopVoiceService()
        if (reason == "client_stop") reduce(AppAction.StopListening)
    }

    private fun stopVoiceService() {
        getApplication<Application>().stopService(
            Intent(getApplication(), VoiceSessionService::class.java),
        )
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
            viewModelScope.launch {
                localState.clearPendingApproval(approval.approvalId)
            }
        } else {
            reduce(AppAction.ReportError("Approval response could not be sent"))
        }
    }

    private fun handleGatewayEvent(event: GatewayEvent) {
        when (event) {
            is GatewayEvent.ConnectionChanged -> {
                reduce(
                    AppAction.SetConnectionState(
                        when (event.state) {
                            GatewayConnectionState.DISCONNECTED -> ConnectionState.DISCONNECTED
                            GatewayConnectionState.CONNECTING -> ConnectionState.CONNECTING
                            GatewayConnectionState.CONNECTED -> ConnectionState.CONNECTED
                            GatewayConnectionState.RECONNECTING -> ConnectionState.RECONNECTING
                        },
                    ),
                )
                if (event.state == GatewayConnectionState.DISCONNECTED) {
                    stopListening("disconnect", sendEvent = false)
                    player.stop()
                } else if (
                    event.state == GatewayConnectionState.CONNECTED &&
                    mutableState.value.conversationActive &&
                    !recorder.isActive
                ) {
                    startListening()
                }
            }
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
                "assistant.state" -> {
                    val state = envelope.payload.getValue("state").jsonPrimitive.content
                    val detail = envelope.payload["detail"]
                        ?.jsonPrimitive
                        ?.contentOrNull
                    reduce(AppAction.SetAssistantState(assistantState(state)))
                    if (detail == "vad_end_detected" && recorder.isActive) {
                        stopListening("vad_end")
                    }
                    if (
                        state == "interrupted" &&
                        mutableState.value.conversationActive &&
                        mutableState.value.connectionState == ConnectionState.CONNECTED
                    ) {
                        startListening()
                    }
                }
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
                "audio.output.chunk" -> {
                    val data = Base64.decode(
                        envelope.payload.getValue("data_base64").jsonPrimitive.content,
                        Base64.DEFAULT,
                    )
                    player.enqueue(
                        data = data,
                        sampleRateHz = envelope.payload.getValue("sample_rate_hz")
                            .jsonPrimitive.int,
                        channels = envelope.payload.getValue("channels").jsonPrimitive.int,
                    )
                }
                "audio.output.end" -> {
                    val reason = envelope.payload.getValue("reason").jsonPrimitive.content
                    if (reason == "completed") {
                        player.finish()
                    } else {
                        player.stop()
                    }
                }
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
                                .jsonArray.joinToString { it.jsonPrimitive.content },
                            impactScope = envelope.payload.getValue("impact_scope")
                                .jsonPrimitive.content,
                            rollback = envelope.payload.getValue("rollback")
                                .jsonPrimitive.content,
                        ),
                    ),
                ).also {
                    val approval = mutableState.value.pendingApproval ?: return@also
                    viewModelScope.launch {
                        localState.savePendingApproval(
                            requestId = envelope.requestId.toString(),
                            sequence = envelope.sequence,
                            approval = approval,
                        )
                    }
                }
                "tool.started", "tool.progress", "tool.completed", "tool.failed",
                "tool.rollback.started", "tool.rollback.completed",
                -> {
                    val summary = "${envelope.type}: " +
                        (envelope.payload["message"]?.jsonPrimitive?.contentOrNull
                            ?: envelope.payload["status"]?.jsonPrimitive?.contentOrNull
                            ?: "updated")
                    reduce(
                        AppAction.SetExecutionSummary(
                            sequence = envelope.sequence,
                            summary = summary,
                        ),
                    )
                    viewModelScope.launch {
                        localState.saveExecutionSummary(envelope.sequence, summary)
                    }
                }
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
