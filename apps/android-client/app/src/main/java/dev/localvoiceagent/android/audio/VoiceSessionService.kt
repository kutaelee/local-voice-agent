package dev.localvoiceagent.android.audio

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.pm.PackageManager
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.content.Intent
import android.os.IBinder
import androidx.core.content.ContextCompat
import dev.localvoiceagent.android.R

class VoiceSessionService : Service() {
    private lateinit var audioManager: AudioManager
    private var selectedCommunicationDevice = false

    override fun onCreate() {
        super.onCreate()
        audioManager = getSystemService(AudioManager::class.java)
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                getString(R.string.voice_service_channel),
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
        selectBluetoothCommunicationDevice()
        val notification = Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.voice_service_active))
            .setOngoing(true)
            .build()
        startForeground(NOTIFICATION_ID, notification)
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        if (Build.VERSION.SDK_INT >= 31 && selectedCommunicationDevice) {
            audioManager.clearCommunicationDevice()
            selectedCommunicationDevice = false
        }
        audioManager.mode = AudioManager.MODE_NORMAL
        super.onDestroy()
    }

    private fun selectBluetoothCommunicationDevice() {
        if (Build.VERSION.SDK_INT < 31 ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val preferredTypes = setOf(
            AudioDeviceInfo.TYPE_BLE_HEADSET,
            AudioDeviceInfo.TYPE_HEARING_AID,
            AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
        )
        val device = audioManager.availableCommunicationDevices.firstOrNull {
            it.type in preferredTypes
        } ?: return
        selectedCommunicationDevice = audioManager.setCommunicationDevice(device)
    }

    companion object {
        private const val CHANNEL_ID = "voice_session"
        private const val NOTIFICATION_ID = 1001
    }
}
