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
        val server = MockWebServer()
        server.useHttps(serverCertificates.sslSocketFactory())
        server.enqueue(
            MockResponse.Builder()
                .webSocketUpgrade(
                    object : WebSocketListener() {
                        override fun onOpen(webSocket: WebSocket, response: Response) {
                            serverSocket.complete(webSocket)
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
            server.close()
        }
    }
}
