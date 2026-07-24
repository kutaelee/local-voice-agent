package dev.localvoiceagent.android.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.media.PlaybackParams
import android.os.SystemClock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicLong

class PcmPlayer(
    context: Context,
    scope: CoroutineScope,
    private val onError: (String) -> Unit,
    private val onPlaybackComplete: () -> Unit,
) {
    private val audioManager = context.getSystemService(AudioManager::class.java)
    private val commands = Channel<Command>(Channel.UNLIMITED)
    private val playbackGeneration = PlaybackGeneration()
    @Volatile private var track: AudioTrack? = null
    @Volatile private var playbackRate = 1.0f
    private var format: PlaybackFormat? = null
    private var focusRequest: AudioFocusRequest? = null
    private var writtenFrames = 0L

    init {
        scope.launch(Dispatchers.IO) {
            for (command in commands) {
                when (command) {
                    is Command.Chunk -> {
                        if (playbackGeneration.isCurrent(command.generation)) {
                            write(command)
                        }
                    }
                    is Command.Finish -> {
                        if (playbackGeneration.isCurrent(command.generation)) {
                            drainAndRelease(command.generation)
                        }
                    }
                    is Command.Abort -> {
                        if (playbackGeneration.isCurrent(command.generation)) {
                            release()
                        }
                    }
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
        commands.trySend(
            Command.Chunk(
                data.copyOf(),
                sampleRateHz,
                channels,
                playbackGeneration.current(),
            ),
        )
    }

    fun finish() {
        commands.trySend(Command.Finish(playbackGeneration.current()))
    }

    fun setPlaybackRate(value: Float) {
        playbackRate = validatedPlaybackRate(value)
        track?.let { activeTrack ->
            runCatching { activeTrack.playbackParams = playbackParameters(playbackRate) }
        }
    }

    fun stop() {
        val generation = playbackGeneration.advance()
        interruptCurrentWrite()
        commands.trySend(Command.Abort(generation))
    }

    fun close() {
        playbackGeneration.advance()
        interruptCurrentWrite()
        commands.close()
    }

    private fun interruptCurrentWrite() {
        track?.let { activeTrack ->
            runCatching { activeTrack.pause() }
            runCatching { activeTrack.flush() }
        }
    }

    private fun write(command: Command.Chunk) {
        if (!playbackGeneration.isCurrent(command.generation)) {
            return
        }
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
        if (!playbackGeneration.isCurrent(command.generation)) {
            release()
            return
        }
        val activeTrack = track ?: return
        val written = activeTrack.write(
            command.data,
            0,
            command.data.size,
            AudioTrack.WRITE_BLOCKING,
        )
        if (shouldReportWriteFailure(
                isCurrent = playbackGeneration.isCurrent(command.generation),
                written = written,
                expected = command.data.size,
            )
        ) {
            onError("Audio playback write failed")
        } else if (written == command.data.size) {
            writtenFrames += written / (command.channels * 2)
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
        created.playbackParams = playbackParameters(playbackRate)
        created.play()
        track = created
        format = playbackFormat
        writtenFrames = 0
    }

    private fun drainAndRelease(generation: Long) {
        val activeTrack = track
        val deadline = SystemClock.elapsedRealtime() + 5_000
        while (
            activeTrack != null &&
            playbackGeneration.isCurrent(generation) &&
            (activeTrack.playbackHeadPosition.toLong() and 0xffff_ffffL) < writtenFrames &&
            SystemClock.elapsedRealtime() < deadline
        ) {
            SystemClock.sleep(10)
        }
        val completed = playbackGeneration.isCurrent(generation)
        release()
        if (completed) onPlaybackComplete()
    }

    private fun release() {
        val activeTrack = track
        track = null
        format = null
        writtenFrames = 0
        if (activeTrack != null) {
            runCatching { activeTrack.pause() }
            runCatching { activeTrack.flush() }
            runCatching { activeTrack.release() }
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
            val generation: Long,
        ) : Command

        data class Finish(val generation: Long) : Command

        data class Abort(val generation: Long) : Command
    }

    private data class PlaybackFormat(
        val sampleRateHz: Int,
        val channels: Int,
    )
}

internal fun shouldReportWriteFailure(
    isCurrent: Boolean,
    written: Int,
    expected: Int,
): Boolean = isCurrent && written != expected

internal fun validatedPlaybackRate(value: Float): Float {
    require(value in 0.85f..1.25f) { "Playback rate is outside the supported range" }
    return value
}

private fun playbackParameters(rate: Float): PlaybackParams = PlaybackParams()
    .setSpeed(rate)
    .setPitch(1.0f)
    .setAudioFallbackMode(PlaybackParams.AUDIO_FALLBACK_MODE_DEFAULT)

internal class PlaybackGeneration {
    private val value = AtomicLong(0)

    fun current(): Long = value.get()

    fun advance(): Long = value.incrementAndGet()

    fun isCurrent(generation: Long): Boolean = value.get() == generation
}
