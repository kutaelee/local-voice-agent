package dev.localvoiceagent.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.localvoiceagent.android.ui.LocalVoiceAgentApp
import dev.localvoiceagent.android.ui.MainViewModel
import dev.localvoiceagent.android.ui.theme.LocalVoiceAgentTheme

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            LocalVoiceAgentTheme {
                LocalVoiceAgentApp(
                    state = viewModel.state.collectAsStateWithLifecycle().value,
                    onAction = viewModel::dispatch,
                )
            }
        }
    }
}
