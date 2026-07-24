package dev.localvoiceagent.android.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ServerEndpointTest {
    @Test
    fun secureOriginBuildsSessionPath() {
        val endpoint = ServerEndpoint.parse("wss://pc.example:8765/")

        assertEquals(
            "wss://pc.example:8765/v1/sessions/session-id/events",
            endpoint.sessionEventsUrl("session-id"),
        )
        assertEquals(
            "https://pc.example:8765/v1/voice/profiles",
            endpoint.managementUrl("/v1/voice/profiles"),
        )
    }

    @Test
    fun cleartextEndpointIsRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            ServerEndpoint.parse("ws://192.168.1.2:8765")
        }
    }

    @Test
    fun credentialsAndApiPathsAreRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            ServerEndpoint.parse("wss://token@pc.example:8765")
        }
        assertThrows(IllegalArgumentException::class.java) {
            ServerEndpoint.parse("wss://pc.example:8765/v1")
        }
    }
}
