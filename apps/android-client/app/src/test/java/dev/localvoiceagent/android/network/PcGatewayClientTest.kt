package dev.localvoiceagent.android.network

import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PcGatewayClientTest {
    @Test
    fun trustedTlsWebSocketSendsBearerAndValidatesServerEnvelope() = runBlocking {
        val certificate = HeldCertificate.Builder()
            .commonName("localhost")
            .addSubjectAlternativeName("localhost")
            .build()
        val serverCertificates = HandshakeCertificates.Builder()
            .heldCertificate(certificate)
            .build()
        val clientCertificates = HandshakeCertificates.Builder()
            .addTrustedCertificate(certificate.certificate)
            .build()
        val serverSocket = CompletableFuture<WebSocket>()
        val serverClosed = CompletableFuture<Unit>()
        val server = MockWebServer()
        server.useHttps(serverCertificates.sslSocketFactory())
        server.enqueue(
            MockResponse.Builder()
                .webSocketUpgrade(
                    object : WebSocketListener() {
                        override fun onOpen(webSocket: WebSocket, response: Response) {
                            serverSocket.complete(webSocket)
                        }

                        override fun onClosed(
                            webSocket: WebSocket,
                            code: Int,
                            reason: String,
                        ) {
                            serverClosed.complete(Unit)
                        }

                        override fun onClosing(
                            webSocket: WebSocket,
                            code: Int,
                            reason: String,
                        ) {
                            webSocket.close(code, reason)
                        }
                    },
                )
                .build(),
        )
        server.start()

        val httpClient = OkHttpClient.Builder()
            .sslSocketFactory(
                clientCertificates.sslSocketFactory(),
                clientCertificates.trustManager,
            )
            .build()
        val gateway = PcGatewayClient(this, httpClient)
        val connected = async {
            gateway.events.first {
                it == GatewayEvent.ConnectionChanged(GatewayConnectionState.CONNECTED)
            }
        }
        val token = "test-only-pairing-token-with-32-chars"
        val origin = server.url("/").toString()
            .replaceFirst("https://", "wss://")
            .trimEnd('/')

        try {
            gateway.connect(origin, token)
            withTimeout(5_000) { connected.await() }

            val request = server.takeRequest(5, TimeUnit.SECONDS)
                ?: error("No WebSocket request received")
            assertEquals("Bearer $token", request.headers["Authorization"])
            assertTrue(request.url.encodedPath.startsWith("/v1/sessions/"))
            val sessionId = request.url.pathSegments[2]

            val message = async {
                gateway.events.first { it is GatewayEvent.Message } as GatewayEvent.Message
            }
            serverSocket.get(5, TimeUnit.SECONDS).send(
                """
                {
                  "schema_version":"1.0",
                  "type":"assistant.state",
                  "session_id":"$sessionId",
                  "request_id":"c0677788-2820-4c0a-b271-b224120380d4",
                  "sequence":0,
                  "timestamp":"2026-07-23T14:00:00Z",
                  "payload":{"state":"connecting","detail":"authenticated"}
                }
                """.trimIndent(),
            )

            assertEquals(
                "assistant.state",
                withTimeout(5_000) { message.await() }.envelope.type,
            )
        } finally {
            gateway.disconnect()
            runCatching { serverClosed.get(5, TimeUnit.SECONDS) }
            server.close()
        }
    }

    @Test
    fun reconnectPreservesSessionAndRequestsEventsAfterLastSequence() = runBlocking {
        class FakeSocket(private val request: okhttp3.Request) : WebSocket {
            override fun request(): okhttp3.Request = request
            override fun queueSize(): Long = 0
            override fun send(text: String): Boolean = true
            override fun send(bytes: okio.ByteString): Boolean = true
            override fun close(code: Int, reason: String?): Boolean = true
            override fun cancel() = Unit
        }

        val requests = mutableListOf<okhttp3.Request>()
        val listeners = mutableListOf<WebSocketListener>()
        val sockets = mutableListOf<FakeSocket>()
        val gateway = PcGatewayClient(
            scope = this,
            socketFactory = { request, listener ->
                requests += request
                listeners += listener
                FakeSocket(request).also { sockets += it }
            },
            reconnectDelayProvider = { 0 },
        )
        val token = "test-only-pairing-token-with-32-chars"
        gateway.connect("wss://localhost:9443", token)
        assertEquals(1, requests.size)
        val sessionId = requests[0].url.pathSegments[2]
        val firstMessage = async(
            start = kotlinx.coroutines.CoroutineStart.UNDISPATCHED,
        ) {
            gateway.events.first {
                it is GatewayEvent.Message && it.envelope.sequence == 5
            } as GatewayEvent.Message
        }
        listeners[0].onMessage(
            sockets[0],
            """
            {
              "schema_version":"1.0",
              "type":"assistant.state",
              "session_id":"$sessionId",
              "request_id":"c0677788-2820-4c0a-b271-b224120380d4",
              "sequence":5,
              "timestamp":"2026-07-23T14:00:00Z",
              "payload":{"state":"listening"}
            }
            """.trimIndent(),
        )
        withTimeout(5_000) { firstMessage.await() }

        listeners[0].onFailure(
            sockets[0],
            java.io.IOException("synthetic transport loss"),
            null,
        )
        withTimeout(5_000) {
            while (requests.size < 2) kotlinx.coroutines.yield()
        }
        assertEquals(requests[0].url.encodedPath, requests[1].url.encodedPath)
        assertEquals("5", requests[1].url.queryParameter("after_sequence"))
        assertEquals("Bearer $token", requests[1].headers["Authorization"])

        val secondMessage = async(
            start = kotlinx.coroutines.CoroutineStart.UNDISPATCHED,
        ) {
            gateway.events.first {
                it is GatewayEvent.Message && it.envelope.sequence == 6
            } as GatewayEvent.Message
        }
        listeners[1].onMessage(
            sockets[1],
            """
            {
              "schema_version":"1.0",
              "type":"assistant.state",
              "session_id":"$sessionId",
              "request_id":"1ff01810-2ced-4ccd-a273-1254436f411c",
              "sequence":6,
              "timestamp":"2026-07-23T14:00:01Z",
              "payload":{"state":"reconnecting"}
            }
            """.trimIndent(),
        )
        assertEquals(
            6,
            withTimeout(5_000) { secondMessage.await() }.envelope.sequence,
        )
        gateway.disconnect()
    }

    @Test
    fun expiredResumeStopsAutomaticReconnectLoop() = runBlocking {
        class FakeSocket(private val request: okhttp3.Request) : WebSocket {
            override fun request(): okhttp3.Request = request
            override fun queueSize(): Long = 0
            override fun send(text: String): Boolean = true
            override fun send(bytes: okio.ByteString): Boolean = true
            override fun close(code: Int, reason: String?): Boolean = true
            override fun cancel() = Unit
        }

        val requests = mutableListOf<okhttp3.Request>()
        val listeners = mutableListOf<WebSocketListener>()
        val sockets = mutableListOf<FakeSocket>()
        val gateway = PcGatewayClient(
            scope = this,
            socketFactory = { request, listener ->
                requests += request
                listeners += listener
                FakeSocket(request).also { sockets += it }
            },
            reconnectDelayProvider = { 0 },
        )
        val failure = async(
            start = kotlinx.coroutines.CoroutineStart.UNDISPATCHED,
        ) {
            gateway.events.first {
                it is GatewayEvent.Failure &&
                    it.code == "SESSION_RESUME_EXPIRED"
            } as GatewayEvent.Failure
        }

        gateway.connect(
            "wss://localhost:9443",
            "test-only-pairing-token-with-32-chars",
        )
        listeners[0].onClosed(sockets[0], 4410, "replay window expired")

        assertEquals(false, withTimeout(5_000) { failure.await() }.retrying)
        kotlinx.coroutines.yield()
        assertEquals(1, requests.size)
        gateway.disconnect()
    }
}
