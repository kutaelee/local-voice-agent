package dev.localvoiceagent.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
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
            Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                Text("Local Voice Agent", style = MaterialTheme.typography.titleLarge)
                Text(
                    "${state.connectionState} · ${state.assistantState}",
                    style = MaterialTheme.typography.labelMedium,
                )
            }
        },
        bottomBar = {
            LazyRow(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
                horizontalArrangement = Arrangement.SpaceEvenly,
            ) {
                items(AppDestination.entries) { destination ->
                    TextButton(onClick = {
                        onAction(AppAction.Navigate(destination))
                    }) {
                        Text(destination.label)
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
                else -> SummaryScreen(state.destination, state)
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
        Button(
            onClick = { onAction(AppAction.StartListening) },
            enabled = state.connectionState == ConnectionState.CONNECTED &&
                state.assistantState != AssistantState.LISTENING,
        ) {
            Text("Start listening")
        }
        Button(
            onClick = { onAction(AppAction.StopListening) },
            enabled = state.assistantState == AssistantState.LISTENING,
        ) {
            Text("Stop")
        }
        Button(onClick = { onAction(AppAction.Interrupt) }) {
            Text("Interrupt")
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
) {
    Text(destination.label, style = MaterialTheme.typography.headlineSmall)
    Spacer(Modifier.height(12.dp))
    val values = when (destination) {
        AppDestination.HISTORY -> listOf("No cached conversations")
        AppDestination.EXECUTION -> listOf(state.executionSummary)
        AppDestination.EVIDENCE -> listOf("No evidence received")
        AppDestination.DIAGNOSTICS -> listOf(
            "Connection: ${state.connectionState}",
            "Assistant: ${state.assistantState}",
            "Server: ${state.serverUrl.ifBlank { "not configured" }}",
        )
        AppDestination.SETTINGS -> listOf("Audio and privacy settings pending")
        else -> emptyList()
    }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(values) { value ->
            Card(Modifier.fillMaxWidth()) {
                Text(value, Modifier.padding(16.dp))
            }
        }
    }
}
