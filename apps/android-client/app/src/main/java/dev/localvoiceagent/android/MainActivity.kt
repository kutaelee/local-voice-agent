package dev.localvoiceagent.android

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.localvoiceagent.android.ui.AppAction
import dev.localvoiceagent.android.ui.LocalVoiceAgentApp
import dev.localvoiceagent.android.ui.MainViewModel
import dev.localvoiceagent.android.ui.theme.LocalVoiceAgentTheme

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            LocalVoiceAgentTheme {
                val state by viewModel.state.collectAsStateWithLifecycle()
                var connectAfterPermission by remember { mutableStateOf(false) }
                var audioActionAfterPermission by remember {
                    mutableStateOf<AppAction?>(null)
                }
                val microphonePermissions = rememberLauncherForActivityResult(
                    ActivityResultContracts.RequestMultiplePermissions(),
                ) { results ->
                    val microphoneGranted =
                        results[Manifest.permission.RECORD_AUDIO] == true ||
                            ContextCompat.checkSelfPermission(
                                this,
                                Manifest.permission.RECORD_AUDIO,
                            ) == PackageManager.PERMISSION_GRANTED
                    val pendingAction = audioActionAfterPermission
                    if (microphoneGranted && pendingAction != null) {
                        viewModel.dispatch(pendingAction)
                    } else if (!microphoneGranted) {
                        viewModel.dispatch(
                            AppAction.ReportError("Microphone permission is required"),
                        )
                    }
                    audioActionAfterPermission = null
                }
                val localNetworkPermission = rememberLauncherForActivityResult(
                    ActivityResultContracts.RequestPermission(),
                ) { granted ->
                    if (granted && connectAfterPermission) {
                        if (
                            ContextCompat.checkSelfPermission(
                                this,
                                Manifest.permission.RECORD_AUDIO,
                            ) != PackageManager.PERMISSION_GRANTED
                        ) {
                            audioActionAfterPermission = AppAction.Connect
                            microphonePermissions.launch(
                                audioPermissions().toTypedArray(),
                            )
                        } else {
                            viewModel.dispatch(AppAction.Connect)
                        }
                    } else if (!granted) {
                        viewModel.dispatch(
                            AppAction.ReportError("Local network permission is required"),
                        )
                    }
                    connectAfterPermission = false
                }
                LocalVoiceAgentApp(
                    state = state,
                    onAction = { action ->
                        if (
                            action == AppAction.Connect &&
                            Build.VERSION.SDK_INT >= 37 &&
                            ContextCompat.checkSelfPermission(
                                this,
                                Manifest.permission.ACCESS_LOCAL_NETWORK,
                            ) != PackageManager.PERMISSION_GRANTED
                        ) {
                            connectAfterPermission = true
                            localNetworkPermission.launch(
                                Manifest.permission.ACCESS_LOCAL_NETWORK,
                            )
                        } else if (
                            action in setOf(
                                AppAction.Connect,
                                AppAction.StartListening,
                                AppAction.StartConversation,
                            ) &&
                            ContextCompat.checkSelfPermission(
                                this,
                                Manifest.permission.RECORD_AUDIO,
                            ) != PackageManager.PERMISSION_GRANTED
                        ) {
                            audioActionAfterPermission = action
                            microphonePermissions.launch(
                                audioPermissions().toTypedArray(),
                            )
                        } else {
                            viewModel.dispatch(action)
                        }
                    },
                )
            }
        }
    }

    private fun audioPermissions(): List<String> = buildList {
        add(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= 33) {
            add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (Build.VERSION.SDK_INT >= 31) {
            add(Manifest.permission.BLUETOOTH_CONNECT)
        }
    }
}
