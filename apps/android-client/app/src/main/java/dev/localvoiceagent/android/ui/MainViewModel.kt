package dev.localvoiceagent.android.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import dev.localvoiceagent.android.security.PairingTokenStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val tokenStore = PairingTokenStore(application)
    private val mutableState = MutableStateFlow(
        AppUiState(pairingConfigured = tokenStore.hasToken()),
    )

    val state: StateFlow<AppUiState> = mutableState.asStateFlow()

    fun dispatch(action: AppAction) {
        if (action is AppAction.SavePairing) {
            runCatching { tokenStore.save(action.token) }
                .onFailure {
                    mutableState.value = AppReducer.reduce(
                        mutableState.value,
                        AppAction.ReportError("Pairing token could not be stored"),
                    )
                    return
                }
        }
        mutableState.value = AppReducer.reduce(mutableState.value, action)
    }
}
