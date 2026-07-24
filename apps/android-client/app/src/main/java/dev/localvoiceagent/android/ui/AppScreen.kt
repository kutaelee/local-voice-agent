package dev.localvoiceagent.android.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

@Composable
fun LocalVoiceAgentApp(
    state: AppUiState,
    onAction: (AppAction) -> Unit,
) {
    Scaffold(
        topBar = {
            Column(
                Modifier
                    .fillMaxWidth()
                    .statusBarsPadding()
                    .padding(horizontal = 16.dp, vertical = 12.dp),
            ) {
                Text("Local Voice Agent", style = MaterialTheme.typography.titleLarge)
                Text(
                    "${state.connectionState} · ${state.assistantState}",
                    style = MaterialTheme.typography.labelMedium,
                )
            }
        },
        bottomBar = {
            val primaryDestinations = listOf(
                AppDestination.PAIRING,
                AppDestination.VOICE,
                AppDestination.APPROVAL,
                AppDestination.DIAGNOSTICS,
            )
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                horizontalArrangement = Arrangement.SpaceEvenly,
            ) {
                primaryDestinations.forEach { destination ->
                    TextButton(
                        onClick = {
                            onAction(AppAction.Navigate(destination))
                        },
                        modifier = Modifier.weight(1f),
                    ) {
                        Text(
                            if (destination == AppDestination.DIAGNOSTICS) {
                                "More"
                            } else {
                                destination.label
                            },
                        )
                    }
                }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
        ) {
            state.lastError?.let {
                Text(it, color = MaterialTheme.colorScheme.error)
                Spacer(Modifier.height(8.dp))
            }
            when (state.destination) {
                AppDestination.PAIRING -> PairingScreen(state, onAction)
                AppDestination.VOICE -> VoiceScreen(state, onAction)
                AppDestination.APPROVAL -> ApprovalScreen(state, onAction)
                AppDestination.SETTINGS -> SettingsScreen(state, onAction)
                else -> SummaryScreen(state.destination, state, onAction)
            }
        }
    }
}

@Composable
private fun PairingScreen(
    state: AppUiState,
    onAction: (AppAction) -> Unit,
) {
    var serverUrl by remember(state.serverUrl) { mutableStateOf(state.serverUrl) }
    var token by remember { mutableStateOf("") }

    Text("PC pairing", style = MaterialTheme.typography.headlineSmall)
    Spacer(Modifier.height(12.dp))
    OutlinedTextField(
        value = serverUrl,
        onValueChange = { serverUrl = it },
        label = { Text("Server URL") },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
    Spacer(Modifier.height(8.dp))
    OutlinedTextField(
        value = token,
        onValueChange = { token = it },
        label = { Text("Pairing token") },
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        modifier = Modifier.fillMaxWidth(),
    )
    Spacer(Modifier.height(12.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = {
            onAction(AppAction.SavePairing(serverUrl, token))
            token = ""
        }) {
            Text("Save securely")
        }
        Button(
            onClick = { onAction(AppAction.Connect) },
            enabled = state.pairingConfigured,
        ) {
            Text("Connect")
        }
    }
}

@Composable
private fun VoiceScreen(
    state: AppUiState,
    onAction: (AppAction) -> Unit,
) {
    Text("Voice conversation", style = MaterialTheme.typography.headlineSmall)
    Text(if (state.conversationActive) "Call active" else "Call paused")
    Spacer(Modifier.height(12.dp))
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text("You: ${state.userTranscript.ifBlank { "—" }}")
            Spacer(Modifier.height(8.dp))
            Text("Agent: ${state.assistantTranscript.ifBlank { "—" }}")
        }
    }
    Spacer(Modifier.height(12.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (state.conversationActive) {
            Button(onClick = { onAction(AppAction.EndConversation) }) {
                Text("End call")
            }
        } else {
            Button(
                onClick = { onAction(AppAction.StartConversation) },
                enabled = state.connectionState == ConnectionState.CONNECTED,
            ) {
                Text("Start call")
            }
        }
        Button(
            onClick = { onAction(AppAction.StopListening) },
            enabled = state.assistantState == AssistantState.LISTENING,
        ) {
            Text("Send now")
        }
        Button(
            onClick = { onAction(AppAction.Interrupt) },
            enabled = state.assistantState in setOf(
                AssistantState.THINKING,
                AssistantState.SYNTHESIZING,
                AssistantState.SPEAKING,
            ),
        ) {
            Text("Interrupt")
        }
    }
}

@Composable
private fun SettingsScreen(
    state: AppUiState,
    onAction: (AppAction) -> Unit,
) {
    var profileName by remember {
        mutableStateOf("My Korean voice")
    }
    var referenceText by remember { mutableStateOf("") }
    var style by remember { mutableStateOf("neutral") }
    var consented by remember { mutableStateOf(false) }
    val filePicker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) {
            onAction(
                AppAction.RegisterVoiceProfile(
                    name = profileName,
                    contentUri = uri.toString(),
                    referenceText = referenceText,
                    style = style,
                    rightsConfirmed = consented,
                    localProcessingConsent = consented,
                ),
            )
        }
    }

    Text("Voice settings", style = MaterialTheme.typography.headlineSmall)
    Spacer(Modifier.height(8.dp))
    LazyColumn(
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        item {
            Text(
                "Reference audio stays on the paired PC and is never bundled in the APK.",
            )
        }
        items(state.voiceProfiles) { profile ->
            Card(Modifier.fillMaxWidth()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    RadioButton(
                        selected = profile.profileId == state.selectedVoiceProfileId,
                        onClick = {
                            onAction(AppAction.SelectVoiceProfile(profile.profileId))
                        },
                        enabled = !state.voiceSettingsBusy,
                    )
                    Column {
                        Text(profile.name)
                        Text(
                            if (profile.isDefault) {
                                "Legacy fallback voice"
                            } else {
                                "Local ${profile.style} reference · ${profile.durationMs ?: 0} ms" +
                                    if (profile.hasReferenceText) {
                                        " · Qwen ready"
                                    } else {
                                        " · legacy only"
                                    }
                            },
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            }
        }
        item {
            Text("Playback speed: ${"%.2f".format(state.voicePlaybackRate)}×")
            Slider(
                value = state.voicePlaybackRate,
                onValueChange = { onAction(AppAction.SetVoicePlaybackRate(it)) },
                valueRange = 0.85f..1.25f,
                steps = 7,
                enabled = !state.voiceSettingsBusy,
            )
        }
        item {
            Text("Fallback expression: ${"%.2f".format(state.voiceExaggeration)}")
            Slider(
                value = state.voiceExaggeration,
                onValueChange = { onAction(AppAction.SetVoiceExaggeration(it)) },
                valueRange = 0.25f..1.0f,
                steps = 14,
                enabled = !state.voiceSettingsBusy,
            )
        }
        item {
            Text("Fallback voice adherence (CFG): ${"%.2f".format(state.voiceCfgWeight)}")
            Slider(
                value = state.voiceCfgWeight,
                onValueChange = { onAction(AppAction.SetVoiceCfgWeight(it)) },
                valueRange = 0.0f..1.0f,
                steps = 19,
                enabled = !state.voiceSettingsBusy,
            )
        }
        item {
            Text("Variation (temperature): ${"%.2f".format(state.voiceTemperature)}")
            Slider(
                value = state.voiceTemperature,
                onValueChange = { onAction(AppAction.SetVoiceTemperature(it)) },
                valueRange = 0.5f..1.2f,
                steps = 13,
                enabled = !state.voiceSettingsBusy,
            )
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = { onAction(AppAction.SaveVoiceSettings) },
                    enabled = !state.voiceSettingsBusy,
                ) {
                    Text("Save voice")
                }
                TextButton(
                    onClick = { onAction(AppAction.RefreshVoiceProfiles) },
                    enabled = !state.voiceSettingsBusy,
                ) {
                    Text("Refresh")
                }
            }
        }
        item {
            Text("Add a reference voice", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(
                value = profileName,
                onValueChange = { profileName = it.take(64) },
                label = { Text("Profile name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(
                value = referenceText,
                onValueChange = { referenceText = it.take(1_000) },
                label = { Text("Exact spoken transcript (required by Qwen3)") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
            )
        }
        item {
            Text("Reference tone")
            Column {
                listOf(
                    "neutral" to "Neutral",
                    "happy" to "Happy",
                    "dark" to "Dark",
                    "advert" to "Advert",
                ).chunked(2).forEach { choices ->
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        choices.forEach { (value, label) ->
                            TextButton(onClick = { style = value }) {
                                Text(
                                    if (style == value) {
                                        "● $label"
                                    } else {
                                        "○ $label"
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Checkbox(
                    checked = consented,
                    onCheckedChange = { consented = it },
                )
                Text(
                    "I own or may use this voice and consent to local storage and processing.",
                )
            }
        }
        item {
            Button(
                onClick = {
                    filePicker.launch(
                        arrayOf("audio/wav", "audio/x-wav", "audio/wave"),
                    )
                },
                enabled = (
                    profileName.isNotBlank() &&
                        referenceText.isNotBlank() &&
                        consented &&
                        !state.voiceSettingsBusy
                    ),
            ) {
                Text("Choose 3–30 second PCM WAV")
            }
        }
        state.voiceSettingsMessage?.let { message ->
            item {
                Text(message, style = MaterialTheme.typography.bodyMedium)
            }
        }
        item {
            Text(
                "Qwen3 uses the exact transcript and temperature. Expression and CFG remain available only for the Chatterbox fallback.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun ApprovalScreen(
    state: AppUiState,
    onAction: (AppAction) -> Unit,
) {
    Text("Tool approval", style = MaterialTheme.typography.headlineSmall)
    Spacer(Modifier.height(12.dp))
    val approval = state.pendingApproval
    if (approval == null) {
        Text("No approval is pending")
    } else {
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                Text("${approval.toolName} · Level ${approval.riskLevel}")
                Text("Target: ${approval.target}")
                Text("Changes: ${approval.expectedChanges}")
                Text("Impact: ${approval.impactScope}")
                Text("Rollback: ${approval.rollback}")
                Text("Digest: ${approval.argumentsDigest}")
            }
        }
    }
    Spacer(Modifier.height(12.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(
            onClick = { onAction(AppAction.ApprovalDecision(true)) },
            enabled = state.pendingApproval != null,
        ) {
            Text("Approve")
        }
        Button(
            onClick = { onAction(AppAction.ApprovalDecision(false)) },
            enabled = state.pendingApproval != null,
        ) {
            Text("Deny")
        }
    }
}

@Composable
private fun SummaryScreen(
    destination: AppDestination,
    state: AppUiState,
    onAction: (AppAction) -> Unit,
) {
    Text(destination.label, style = MaterialTheme.typography.headlineSmall)
    Spacer(Modifier.height(12.dp))
    val values = when (destination) {
        AppDestination.HISTORY -> listOf(
            "Transcript retention is disabled by default for privacy",
        )
        AppDestination.EXECUTION -> listOf(state.executionSummary)
        AppDestination.EVIDENCE -> listOf("No evidence received")
        AppDestination.DIAGNOSTICS -> listOf(
            "Connection: ${state.connectionState}",
            "Assistant: ${state.assistantState}",
            "Server: ${state.serverUrl.ifBlank { "not configured" }}",
        )
        AppDestination.SETTINGS -> emptyList()
        else -> emptyList()
    }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(values) { value ->
            Card(Modifier.fillMaxWidth()) {
                Text(value, Modifier.padding(16.dp))
            }
        }
        if (destination == AppDestination.DIAGNOSTICS) {
            item {
                Text("More screens", style = MaterialTheme.typography.titleMedium)
            }
            items(
                listOf(
                    AppDestination.HISTORY,
                    AppDestination.EXECUTION,
                    AppDestination.EVIDENCE,
                    AppDestination.SETTINGS,
                ),
            ) { target ->
                Button(
                    onClick = { onAction(AppAction.Navigate(target)) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(target.label)
                }
            }
        }
    }
}
