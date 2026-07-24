package dev.localvoiceagent.android.network

import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Assert.assertEquals
import org.junit.Test

class VoiceProfileClientTest {
    @Test
    fun catalogUsesAuthenticatedHttpsManagementRoute() = runBlocking {
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
        val server = MockWebServer()
        server.useHttps(serverCertificates.sslSocketFactory())
        server.enqueue(
            MockResponse.Builder()
                .code(200)
                .body(
                    """
                    {
                      "schema_version":"1.0",
                      "profiles":[
                        {
                          "profile_id":"default",
                          "name":"Default Korean",
                          "is_default":true,
                          "created_at":null,
                          "sha256":null,
                          "size_bytes":null,
                          "duration_ms":null,
                          "sample_rate_hz":null,
                          "channels":null
                        }
                      ],
                      "settings":{
                        "profile_id":"default",
                        "playback_rate":1.0,
                        "exaggeration":0.5,
                        "cfg_weight":0.5,
                        "temperature":0.8
                      }
                    }
                    """.trimIndent(),
                )
                .build(),
        )
        server.start()
        val client = VoiceProfileClient(
            OkHttpClient.Builder()
                .sslSocketFactory(
                    clientCertificates.sslSocketFactory(),
                    clientCertificates.trustManager,
                )
                .build(),
        )
        val token = "test-only-pairing-token-with-32-chars"
        val endpoint = ServerEndpoint.parse(
            server.url("/").toString()
                .replaceFirst("https://", "wss://")
                .trimEnd('/'),
        )

        try {
            val catalog = client.catalog(endpoint, token)
            val request = server.takeRequest(5, TimeUnit.SECONDS)
                ?: error("No voice profile request received")

            assertEquals("/v1/voice/profiles", request.url.encodedPath)
            assertEquals("Bearer $token", request.headers["Authorization"])
            assertEquals("default", catalog.settings.profileId)
        } finally {
            server.close()
        }
    }
}
