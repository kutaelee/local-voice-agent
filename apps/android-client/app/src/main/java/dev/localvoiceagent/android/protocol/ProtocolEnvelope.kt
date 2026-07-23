package dev.localvoiceagent.android.protocol

import java.time.OffsetDateTime
import java.util.UUID
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

data class ProtocolEnvelope(
    val type: String,
    val sessionId: UUID,
    val requestId: UUID,
    val sequence: Int,
    val timestamp: OffsetDateTime,
    val payload: JsonObject,
) {
    fun encode(): String = buildJsonObject {
        put("schema_version", SCHEMA_VERSION)
        put("type", type)
        put("session_id", sessionId.toString())
        put("request_id", requestId.toString())
        put("sequence", sequence)
        put("timestamp", timestamp.toString())
        put("payload", payload)
    }.toString()

    companion object {
        const val SCHEMA_VERSION = "1.0"

        private val envelopeKeys = setOf(
            "schema_version",
            "type",
            "session_id",
            "request_id",
            "sequence",
            "timestamp",
            "payload",
        )

        val serverEventTypes = setOf(
            "transcript.user.partial",
            "transcript.user.final",
            "assistant.state",
            "assistant.text.delta",
            "assistant.text.final",
            "audio.output.chunk",
            "audio.output.end",
            "tool.plan",
            "tool.approval.required",
            "tool.started",
            "tool.progress",
            "tool.completed",
            "tool.failed",
            "tool.rollback.started",
            "tool.rollback.completed",
            "model.switch.started",
            "model.switch.completed",
            "operation.cancel.result",
            "error",
        )

        val clientEventTypes = setOf(
            "audio.input.chunk",
            "audio.input.start",
            "audio.input.end",
            "tool.approval.response",
            "operation.cancel.requested",
            "error",
        )

        fun parse(raw: String): ProtocolEnvelope {
            val value = Json.parseToJsonElement(raw).jsonObject
            require(value.keys == envelopeKeys) { "Envelope fields are invalid" }
            require(value.getValue("schema_version").jsonPrimitive.content == SCHEMA_VERSION) {
                "Schema version is unsupported"
            }
            val type = value.getValue("type").jsonPrimitive.content
            require(type in serverEventTypes) { "Server event type is unsupported" }
            val sequence = value.getValue("sequence").jsonPrimitive.int
            require(sequence >= 0) { "Sequence cannot be negative" }

            return ProtocolEnvelope(
                type = type,
                sessionId = UUID.fromString(
                    value.getValue("session_id").jsonPrimitive.content,
                ),
                requestId = UUID.fromString(
                    value.getValue("request_id").jsonPrimitive.content,
                ),
                sequence = sequence,
                timestamp = OffsetDateTime.parse(
                    value.getValue("timestamp").jsonPrimitive.content,
                ),
                payload = value.getValue("payload").jsonObject,
            )
        }

        fun createClient(
            type: String,
            sessionId: UUID,
            requestId: UUID = UUID.randomUUID(),
            sequence: Int,
            payload: JsonObject,
        ): ProtocolEnvelope {
            require(type in clientEventTypes) { "Client event type is unsupported" }
            require(sequence >= 0) { "Sequence cannot be negative" }
            return ProtocolEnvelope(
                type = type,
                sessionId = sessionId,
                requestId = requestId,
                sequence = sequence,
                timestamp = OffsetDateTime.now(),
                payload = payload,
            )
        }
    }
}
