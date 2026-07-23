package dev.localvoiceagent.android.storage

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Transaction
import dev.localvoiceagent.android.ui.PendingApproval
import java.util.UUID

@Entity(tableName = "pending_approvals")
data class PendingApprovalEntity(
    @PrimaryKey val approvalId: String,
    val requestId: String,
    val sequence: Int,
    val toolName: String,
    val riskLevel: Int,
    val target: String,
    val argumentsDigest: String,
    val expectedChanges: String,
    val impactScope: String,
    val rollback: String,
    val storedAtEpochMs: Long,
)

@Entity(tableName = "execution_summaries")
data class ExecutionSummaryEntity(
    @PrimaryKey val id: String,
    val sequence: Int,
    val summary: String,
    val storedAtEpochMs: Long,
)

@Dao
interface LocalStateDao {
    @Query("SELECT * FROM pending_approvals ORDER BY storedAtEpochMs DESC LIMIT 1")
    suspend fun latestPendingApproval(): PendingApprovalEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertPendingApproval(entity: PendingApprovalEntity)

    @Query("DELETE FROM pending_approvals")
    suspend fun deleteAllPendingApprovals()

    @Transaction
    suspend fun replacePendingApproval(entity: PendingApprovalEntity) {
        deleteAllPendingApprovals()
        upsertPendingApproval(entity)
    }

    @Query("DELETE FROM pending_approvals WHERE approvalId = :approvalId")
    suspend fun deletePendingApproval(approvalId: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertExecutionSummary(entity: ExecutionSummaryEntity)

    @Query("DELETE FROM execution_summaries WHERE id NOT IN (SELECT id FROM execution_summaries ORDER BY storedAtEpochMs DESC LIMIT 50)")
    suspend fun retainLatestExecutionSummaries()

    @Query("SELECT * FROM execution_summaries ORDER BY storedAtEpochMs DESC LIMIT 1")
    suspend fun latestExecutionSummary(): ExecutionSummaryEntity?
}

@Database(
    entities = [PendingApprovalEntity::class, ExecutionSummaryEntity::class],
    version = 1,
    exportSchema = true,
)
abstract class LocalStateDatabase : RoomDatabase() {
    abstract fun localStateDao(): LocalStateDao
}

data class RestoredLocalState(
    val pendingApproval: PendingApproval? = null,
    val pendingRequestId: String? = null,
    val pendingSequence: Int = -1,
    val latestExecutionSummary: String? = null,
    val latestExecutionSequence: Int = -1,
)

/**
 * Stores only pending approval details and bounded execution metadata. Raw
 * microphone input and full transcript content intentionally never enter the
 * local database without a future, explicit privacy setting.
 */
class LocalStateStore private constructor(
    private val dao: LocalStateDao,
) {
    suspend fun restore(): RestoredLocalState {
        val pending = dao.latestPendingApproval()
        val execution = dao.latestExecutionSummary()
        return RestoredLocalState(
            pendingApproval = pending?.toDomain(),
            pendingRequestId = pending?.requestId,
            pendingSequence = pending?.sequence ?: -1,
            latestExecutionSummary = execution?.summary,
            latestExecutionSequence = execution?.sequence ?: -1,
        )
    }

    suspend fun savePendingApproval(
        requestId: String,
        sequence: Int,
        approval: PendingApproval,
    ) {
        dao.replacePendingApproval(
            PendingApprovalEntity(
                approvalId = approval.approvalId,
                requestId = requestId,
                sequence = sequence,
                toolName = approval.toolName,
                riskLevel = approval.riskLevel,
                target = approval.target,
                argumentsDigest = approval.argumentsDigest,
                expectedChanges = approval.expectedChanges,
                impactScope = approval.impactScope,
                rollback = approval.rollback,
                storedAtEpochMs = System.currentTimeMillis(),
            ),
        )
    }

    suspend fun clearPendingApproval(approvalId: String) {
        dao.deletePendingApproval(approvalId)
    }

    suspend fun saveExecutionSummary(sequence: Int, summary: String) {
        dao.insertExecutionSummary(
            ExecutionSummaryEntity(
                id = UUID.randomUUID().toString(),
                sequence = sequence,
                summary = summary.take(MAX_SUMMARY_LENGTH),
                storedAtEpochMs = System.currentTimeMillis(),
            ),
        )
        dao.retainLatestExecutionSummaries()
    }

    private fun PendingApprovalEntity.toDomain(): PendingApproval = PendingApproval(
        approvalId = approvalId,
        toolName = toolName,
        riskLevel = riskLevel,
        target = target,
        argumentsDigest = argumentsDigest,
        expectedChanges = expectedChanges,
        impactScope = impactScope,
        rollback = rollback,
    )

    companion object {
        private const val DATABASE_NAME = "local_voice_agent_state.db"
        private const val MAX_SUMMARY_LENGTH = 1_024

        fun create(context: Context): LocalStateStore = LocalStateStore(
            Room.databaseBuilder(
                context.applicationContext,
                LocalStateDatabase::class.java,
                DATABASE_NAME,
            ).build().localStateDao(),
        )
    }
}
