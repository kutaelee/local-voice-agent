package dev.localvoiceagent.android.network

import java.net.URI

class ServerEndpoint private constructor(
    val baseUrl: String,
) {
    fun sessionEventsUrl(
        sessionId: String,
        afterSequence: Int? = null,
    ): String {
        require(afterSequence == null || afterSequence >= -1) {
            "Resume sequence is invalid"
        }
        val query = afterSequence?.let { "?after_sequence=$it" } ?: ""
        return "$baseUrl/v1/sessions/$sessionId/events$query"
    }

    companion object {
        fun parse(value: String): ServerEndpoint {
            val trimmed = value.trim().trimEnd('/')
            val uri = runCatching { URI(trimmed) }
                .getOrElse { throw IllegalArgumentException("Server URL is invalid") }

            require(uri.scheme.equals("wss", ignoreCase = true)) {
                "A secure wss:// server URL is required"
            }
            require(!uri.host.isNullOrBlank()) { "Server host is required" }
            require(uri.userInfo == null) { "Credentials are not allowed in the URL" }
            require(uri.query == null && uri.fragment == null) {
                "Query strings and fragments are not allowed"
            }
            require(uri.path.isNullOrBlank() || uri.path == "/") {
                "Enter only the server origin, without an API path"
            }
            return ServerEndpoint(trimmed)
        }
    }
}
