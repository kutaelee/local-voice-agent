package dev.localvoiceagent.android.audio

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaybackGenerationTest {
    @Test
    fun abortInvalidatesEveryQueuedChunkFromThePreviousGeneration() {
        val generations = PlaybackGeneration()
        val queuedChunk = generations.current()

        val replacementGeneration = generations.advance()

        assertFalse(generations.isCurrent(queuedChunk))
        assertTrue(generations.isCurrent(replacementGeneration))
    }

    @Test
    fun normalDrainKeepsQueuedChunksInTheCurrentGeneration() {
        val generations = PlaybackGeneration()
        val queuedChunk = generations.current()

        assertTrue(generations.isCurrent(queuedChunk))
    }
}
