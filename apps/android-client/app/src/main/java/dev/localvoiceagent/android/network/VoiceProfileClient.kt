package dev.localvoiceagent.android.network

import java.io.IOException
import java.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

@Serializable
data class VoiceProfileSummary(
    @SerialName("profile_id") val profileId: String,
    val name: String,
    @SerialName("is_default") val isDefault: Boolean,
    @SerialName("created_at") val createdAt: String? = null,
    val sha256: String? = null,
    @SerialName("size_bytes") val sizeBytes: Int? = null,
    @SerialName("duration_ms") val durationMs: Int? = null,
    @SerialName("sample_rate_hz") val sampleRateHz: Int? = null,
    val channels: Int? = null,
    val style: String = "neutral",
    @SerialName("has_reference_text") val hasReferenceText: Boolean = false,
)

@Serializable
data class VoiceSettingsDto(
    @SerialName("profile_id") val profileId: String,
    @SerialName("playback_rate") val playbackRate: Float,
    val exaggeration: Float,
    @SerialName("cfg_weight") val cfgWeight: Float,
    val temperature: Float,
)

@Serializable
data class VoiceProfileCatalog(
    @SerialName("schema_version") val schemaVersion: String,
    val profiles: List<VoiceProfileSummary>,
    val settings: VoiceSettingsDto,
)

@Serializable
private data class CreateVoiceProfilePayload(
    val name: String,
    @SerialName("wav_base64") val wavBase64: String,
    @SerialName("rights_confirmed") val rightsConfirmed: Boolean,
    @SerialName("local_processing_consent") val localProcessingConsent: Boolean,
    @SerialName("reference_text") val referenceText: String,
    val style: String,
)

@Serializable
private data class CreateVoiceProfileResponse(
    @SerialName("schema_version") val schemaVersion: String,
    val profile: VoiceProfileSummary,
)

@Serializable
private data class UpdateVoiceSettingsResponse(
    @SerialName("schema_version") val schemaVersion: String,
    val settings: VoiceSettingsDto,
)

class VoiceProfileApiException(
    message: String,
    cause: Throwable? = null,
) : IOException(message, cause)

class VoiceProfileClient(
    private val httpClient: OkHttpClient = OkHttpClient(),
) {
    private val json = Json {
        ignoreUnknownKeys = false
        explicitNulls = false
    }

    suspend fun catalog(
        endpoint: ServerEndpoint,
        token: String,
    ): VoiceProfileCatalog = request(
        Request.Builder()
            .url(endpoint.managementUrl("/v1/voice/profiles"))
            .header("Authorization", "Bearer $token")
            .get()
            .build(),
    )

    suspend fun create(
        endpoint: ServerEndpoint,
        token: String,
        name: String,
        wav: ByteArray,
        rightsConfirmed: Boolean,
        localProcessingConsent: Boolean,
        referenceText: String,
        style: String,
    ): VoiceProfileSummary {
        require(wav.isNotEmpty() && wav.size <= MAX_REFERENCE_BYTES) {
            "Reference WAV size is invalid"
        }
        require(referenceText.isNotBlank() && referenceText.length <= 1_000) {
            "Reference transcript is invalid"
        }
        require(style in SUPPORTED_STYLES) { "Reference style is invalid" }
        val payload = CreateVoiceProfilePayload(
            name = name,
            wavBase64 = Base64.getEncoder().encodeToString(wav),
            rightsConfirmed = rightsConfirmed,
            localProcessingConsent = localProcessingConsent,
            referenceText = referenceText.trim(),
            style = style,
        )
        return request<CreateVoiceProfileResponse>(
            Request.Builder()
                .url(endpoint.managementUrl("/v1/voice/profiles"))
                .header("Authorization", "Bearer $token")
                .post(
                    json.encodeToString(payload).toRequestBody(JSON_MEDIA_TYPE),
                )
                .build(),
        ).profile
    }

    suspend fun updateSettings(
        endpoint: ServerEndpoint,
        token: String,
        settings: VoiceSettingsDto,
    ): VoiceSettingsDto = request<UpdateVoiceSettingsResponse>(
        Request.Builder()
            .url(endpoint.managementUrl("/v1/voice/settings"))
            .header("Authorization", "Bearer $token")
            .put(
                json.encodeToString(settings).toRequestBody(JSON_MEDIA_TYPE),
            )
            .build(),
    ).settings

    private suspend inline fun <reified T> request(request: Request): T =
        withContext(Dispatchers.IO) {
            httpClient.newCall(request).execute().use { response ->
                val body = response.body.string()
                if (!response.isSuccessful) {
                    throw VoiceProfileApiException(
                        "Voice settings request failed (${response.code})",
                    )
                }
                runCatching { json.decodeFromString<T>(body) }
                    .getOrElse { error ->
                        throw VoiceProfileApiException(
                            "Voice settings response is invalid",
                            error,
                        )
                    }
            }
        }

    companion object {
        const val MAX_REFERENCE_BYTES = 8 * 1024 * 1024
        val SUPPORTED_STYLES = setOf("neutral", "happy", "dark", "advert")
        private val JSON_MEDIA_TYPE = "application/json".toMediaType()
    }
}
