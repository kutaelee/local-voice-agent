package dev.localvoiceagent.android.audio

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

class PcmRecorder(
    private val context: Context,
    private val scope: CoroutineScope,
    private val onChunk: (ByteArray, Int) -> Unit,
    private val onError: (String) -> Unit,
) {
    private val active = AtomicBoolean(false)
    private var recorder: AudioRecord? = null
    private var job: Job? = null

    val isActive: Boolean
        get() = active.get()

    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        if (active.get()) return false
        if (
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            onError("Microphone permission is required")
            return false
        }
        val minimum = AudioRecord.getMinBufferSize(
            SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minimum <= 0) {
            onError("Audio input buffer is unavailable")
            return false
        }
        val bufferBytes = maxOf(minimum, TARGET_CHUNK_BYTES)
        val created = AudioRecord.Builder()
            .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(SAMPLE_RATE_HZ)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .build(),
            )
            .setBufferSizeInBytes(bufferBytes * 2)
            .build()
        if (created.state != AudioRecord.STATE_INITIALIZED) {
            created.release()
            onError("Audio input initialization failed")
            return false
        }
        recorder = created
        active.set(true)
        job = scope.launch(Dispatchers.IO) {
            val buffer = ByteArray(bufferBytes)
            try {
                created.startRecording()
                while (active.get()) {
                    val count = created.read(
                        buffer,
                        0,
                        buffer.size,
                        AudioRecord.READ_BLOCKING,
                    )
                    if (count > 0) {
                        val aligned = count - (count % BYTES_PER_FRAME)
                        if (aligned > 0) {
                            val durationMs = maxOf(
                                1,
                                aligned * 1_000 / (SAMPLE_RATE_HZ * BYTES_PER_FRAME),
                            )
                            onChunk(buffer.copyOf(aligned), durationMs)
                        }
                    } else if (count < 0 && active.get()) {
                        onError("Audio input read failed: $count")
                        break
                    }
                }
            } catch (_: SecurityException) {
                onError("Microphone permission was revoked")
            } catch (_: IllegalStateException) {
                if (active.get()) onError("Audio input stopped unexpectedly")
            } finally {
                active.set(false)
                runCatching { created.stop() }
                created.release()
                if (recorder === created) recorder = null
            }
        }
        return true
    }

    fun stop() {
        if (!active.getAndSet(false)) return
        runCatching { recorder?.stop() }
        job?.cancel()
        job = null
    }

    companion object {
        const val SAMPLE_RATE_HZ = 16_000
        const val CHANNELS = 1
        private const val BYTES_PER_FRAME = 2
        private const val TARGET_CHUNK_BYTES = 3_200
    }
}
