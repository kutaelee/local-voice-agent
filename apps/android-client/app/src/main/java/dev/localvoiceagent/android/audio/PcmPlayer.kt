package dev.localvoiceagent.android.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch

class PcmPlayer(
    context: Context,
    scope: CoroutineScope,
    private val onError: (String) -> Unit,
) {
    private val audioManager = context.getSystemService(AudioManager::class.java)
    private val commands = Channel<Command>(Channel.UNLIMITED)
    private var track: AudioTrack? = null
    private var format: PlaybackFormat? = null
    private var focusRequest: AudioFocusRequest? = null

    init {
        scope.launch(Dispatchers.IO) {
            for (command in commands) {
                when (command) {
                    is Command.Chunk -> write(command)
                    Command.Stop -> release()
                }
            }
            release()
        }
    }

    fun enqueue(data: ByteArray, sampleRateHz: Int, channels: Int) {
        if (data.isEmpty() || data.size > 384 * 1024 || data.size % 2 != 0) {
            onError("Server audio chunk size is invalid")
            return
        }
        commands.trySend(Command.Chunk(data.copyOf(), sampleRateHz, channels))
    }

    fun stop() {
        commands.trySend(Command.Stop)
    }

    fun close() {
        commands.close()
    }

    private fun write(command: Command.Chunk) {
        val incomingFormat = PlaybackFormat(command.sampleRateHz, command.channels)
        if (incomingFormat.sampleRateHz !in setOf(16_000, 24_000, 48_000)) {
            onError("Server audio sample rate is unsupported")
            return
        }
        if (incomingFormat.channels !in setOf(1, 2)) {
            onError("Server audio channel count is unsupported")
            return
        }
        if (track == null) {
            createTrack(incomingFormat)
        } else if (format != incomingFormat) {
            release()
            createTrack(incomingFormat)
        }
        val activeTrack = track ?: return
        val written = activeTrack.write(
            command.data,
            0,
            command.data.size,
            AudioTrack.WRITE_BLOCKING,
        )
        if (written != command.data.size) {
            onError("Audio playback write failed")
        }
    }

    private fun createTrack(playbackFormat: PlaybackFormat) {
        val channelMask = if (playbackFormat.channels == 1) {
            AudioFormat.CHANNEL_OUT_MONO
        } else {
            AudioFormat.CHANNEL_OUT_STEREO
        }
        val minimum = AudioTrack.getMinBufferSize(
            playbackFormat.sampleRateHz,
            channelMask,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minimum <= 0) {
            onError("Audio playback buffer is unavailable")
            return
        }
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attributes)
            .setAcceptsDelayedFocusGain(false)
            .build()
        if (audioManager.requestAudioFocus(request) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            onError("Audio focus was not granted")
            return
        }
        audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
        focusRequest = request
        val created = AudioTrack.Builder()
            .setAudioAttributes(attributes)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(playbackFormat.sampleRateHz)
                    .setChannelMask(channelMask)
                    .build(),
            )
            .setBufferSizeInBytes(maxOf(minimum, playbackFormat.sampleRateHz))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        created.play()
        track = created
        format = playbackFormat
    }

    private fun release() {
        val activeTrack = track
        track = null
        format = null
        if (activeTrack != null) {
            runCatching { activeTrack.pause() }
            activeTrack.flush()
            activeTrack.release()
        }
        focusRequest?.let(audioManager::abandonAudioFocusRequest)
        focusRequest = null
        audioManager.mode = AudioManager.MODE_NORMAL
    }

    private sealed interface Command {
        data class Chunk(
            val data: ByteArray,
            val sampleRateHz: Int,
            val channels: Int,
        ) : Command

        data object Stop : Command
    }

    private data class PlaybackFormat(
        val sampleRateHz: Int,
        val channels: Int,
    )
}
