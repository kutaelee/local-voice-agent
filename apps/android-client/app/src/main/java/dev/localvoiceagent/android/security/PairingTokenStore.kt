package dev.localvoiceagent.android.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class PairingTokenStore(context: Context) {
    private val preferences = context.getSharedPreferences(
        "secure_pairing",
        Context.MODE_PRIVATE,
    )

    fun hasToken(): Boolean = preferences.contains(CIPHERTEXT_KEY)

    fun save(token: String) {
        require(token.length in 32..4096) { "Pairing token length is invalid" }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(token.encodeToByteArray())
        preferences.edit {
            putString(IV_KEY, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            putString(
                CIPHERTEXT_KEY,
                Base64.encodeToString(encrypted, Base64.NO_WRAP),
            )
        }
    }

    fun load(): String? {
        val iv = preferences.getString(IV_KEY, null) ?: return null
        val encrypted = preferences.getString(CIPHERTEXT_KEY, null) ?: return null
        return runCatching {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                getOrCreateKey(),
                GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
            )
            cipher.doFinal(
                Base64.decode(encrypted, Base64.NO_WRAP),
            ).decodeToString()
        }.getOrNull()
    }

    fun clear() {
        preferences.edit {
            remove(IV_KEY)
            remove(CIPHERTEXT_KEY)
        }
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE_PROVIDER).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }

        return KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            KEYSTORE_PROVIDER,
        ).run {
            init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build(),
            )
            generateKey()
        }
    }

    private companion object {
        const val KEYSTORE_PROVIDER = "AndroidKeyStore"
        const val KEY_ALIAS = "local_voice_agent_pairing_v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_KEY = "iv"
        const val CIPHERTEXT_KEY = "ciphertext"
    }
}
