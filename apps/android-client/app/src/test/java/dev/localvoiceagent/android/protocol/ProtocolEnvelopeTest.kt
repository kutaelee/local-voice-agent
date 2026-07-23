package dev.localvoiceagent.android.protocol

import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ProtocolEnvelopeTest {
    private val sessionId = UUID.randomUUID()
    private val requestId = UUID.randomUUID()

    @Test
    fun validServerEnvelopeParses() {
        val envelope = ProtocolEnvelope.parse(
            """
            {
              "schema_version":"1.0",
              "type":"assistant.state",
              "session_id":"$sessionId",
              "request_id":"$requestId",
              "sequence":0,
              "timestamp":"2026-07-23T14:00:00Z",
              "payload":{"state":"connecting","detail":"authenticated"}
            }
            """.trimIndent(),
        )

        assertEquals("assistant.state", envelope.type)
        assertEquals(sessionId, envelope.sessionId)
        assertEquals(0, envelope.sequence)
    }

    @Test
    fun unknownEnvelopeFieldsAreRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            ProtocolEnvelope.parse(
                """
                {
                  "schema_version":"1.0",
                  "type":"assistant.state",
                  "session_id":"$sessionId",
                  "request_id":"$requestId",
                  "sequence":0,
                  "timestamp":"2026-07-23T14:00:00Z",
                  "payload":{"state":"connecting"},
                  "unexpected":true
                }
                """.trimIndent(),
            )
        }
    }

    @Test
    fun naiveTimestampAndUnknownTypeAreRejected() {
        assertThrows(Exception::class.java) {
            ProtocolEnvelope.parse(
                """
                {
                  "schema_version":"1.0",
                  "type":"assistant.state",
                  "session_id":"$sessionId",
                  "request_id":"$requestId",
                  "sequence":0,
                  "timestamp":"2026-07-23T14:00:00",
                  "payload":{"state":"connecting"}
                }
                """.trimIndent(),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            ProtocolEnvelope.parse(
                """
                {
                  "schema_version":"1.0",
                  "type":"unknown.event",
                  "session_id":"$sessionId",
                  "request_id":"$requestId",
                  "sequence":0,
                  "timestamp":"2026-07-23T14:00:00Z",
                  "payload":{}
                }
                """.trimIndent(),
            )
        }
    }
}
