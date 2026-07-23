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
                val localNetworkPermission = rememberLauncherForActivityResult(
                    ActivityResultContracts.RequestPermission(),
                ) { granted ->
                    if (granted && connectAfterPermission) {
                        viewModel.dispatch(AppAction.Connect)
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
                        } else {
                            viewModel.dispatch(action)
                        }
                    },
                )
            }
        }
    }
}
