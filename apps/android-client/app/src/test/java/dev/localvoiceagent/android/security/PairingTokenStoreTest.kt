package dev.localvoiceagent.android.security

import org.junit.Assert.assertEquals
import org.junit.Test

class PairingTokenStoreTest {
    @Test
    fun migratesLegacySecureGatewayPort() {
        assertEquals(
            "wss://192.168.200.94:46321",
            migrateLegacyServerUrl("wss://192.168.200.94:8765"),
        )
    }

    @Test
    fun preservesOtherEndpoints() {
        assertEquals(
            "wss://pc.example:443",
            migrateLegacyServerUrl("wss://pc.example:443"),
        )
        assertEquals(
            "ws://192.168.200.94:8765",
            migrateLegacyServerUrl("ws://192.168.200.94:8765"),
        )
    }
}
