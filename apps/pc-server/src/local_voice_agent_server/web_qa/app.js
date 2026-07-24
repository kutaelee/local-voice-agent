const $ = (id) => document.getElementById(id);
const ui = {
  connectionBadge: $("connectionBadge"),
  assistantBadge: $("assistantBadge"),
  serverUrl: $("serverUrl"),
  pairingToken: $("pairingToken"),
  connectButton: $("connectButton"),
  diagnoseButton: $("diagnoseButton"),
  diagnostics: $("diagnostics"),
  conversation: $("conversation"),
  autoContinue: $("autoContinue"),
  startButton: $("startButton"),
  stopButton: $("stopButton"),
  interruptButton: $("interruptButton"),
  statusLine: $("statusLine"),
  sttMetric: $("sttMetric"),
  llmMetric: $("llmMetric"),
  ttsMetric: $("ttsMetric"),
  gapMetric: $("gapMetric"),
  micMeter: $("micMeter"),
  resetMetricsButton: $("resetMetricsButton"),
  voiceProfile: $("voiceProfile"),
  playbackRate: $("playbackRate"),
  rateValue: $("rateValue"),
  exaggeration: $("exaggeration"),
  emotionValue: $("emotionValue"),
  cfgWeight: $("cfgWeight"),
  cfgValue: $("cfgValue"),
  temperature: $("temperature"),
  temperatureValue: $("temperatureValue"),
  saveVoiceButton: $("saveVoiceButton"),
  approvalCard: $("approvalCard"),
  approvalTitle: $("approvalTitle"),
  riskBadge: $("riskBadge"),
  approvalDetails: $("approvalDetails"),
  approvalArguments: $("approvalArguments"),
  approveButton: $("approveButton"),
  rejectButton: $("rejectButton"),
  events: $("events"),
  clearEventsButton: $("clearEventsButton"),
  toast: $("toast"),
};

const state = {
  socket: null,
  qaAccessToken: null,
  sessionId: crypto.randomUUID(),
  sequence: 0,
  connected: false,
  listening: false,
  manuallyStopped: false,
  inputStreamId: null,
  inputChunkIndex: 0,
  currentRequestId: null,
  mediaStream: null,
  audioContext: null,
  captureSource: null,
  captureNode: null,
  captureGain: null,
  playbackSources: new Set(),
  playbackChain: Promise.resolve(),
  playbackGeneration: 0,
  nextPlaybackTime: 0,
  playbackEndTimer: null,
  pendingApproval: null,
  assistantMessage: null,
  metrics: {},
  turn: {},
};

const assistantLabels = {
  connecting: "연결 중",
  idle: "대기",
  listening: "듣는 중",
  recognizing: "인식 중",
  thinking: "생각 중",
  selecting_tool: "도구 선택",
  waiting_approval: "승인 대기",
  executing: "실행 중",
  verifying: "검증 중",
  synthesizing: "음성 합성",
  speaking: "말하는 중",
  interrupted: "중단됨",
  switching_model: "모델 전환",
  reconnecting: "재연결",
  error: "오류",
};

function normalizedBaseUrl() {
  const raw = ui.serverUrl.value.trim().replace(/\/+$/, "");
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("HTTP 또는 HTTPS 서버 URL이 필요합니다.");
  }
  return url.toString().replace(/\/$/, "");
}

function authHeaders() {
  const token = ui.pairingToken.value || state.qaAccessToken || "";
  if (token.length < 32) throw new Error("페어링 토큰을 확인하세요.");
  return { Authorization: `Bearer ${token}` };
}

function canUseLocalQaBootstrap() {
  try {
    const server = new URL(normalizedBaseUrl());
    return (
      server.origin === location.origin
      && ["127.0.0.1", "localhost", "[::1]"].includes(server.hostname)
    );
  } catch {
    return false;
  }
}

async function bootstrapLocalQa() {
  const response = await fetch(`${normalizedBaseUrl()}/v1/qa/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || typeof body.access_token !== "string") {
    throw new Error(
      body.detail || "로컬 QA 자동 인증을 시작하지 못했습니다.",
    );
  }
  state.qaAccessToken = body.access_token;
  ui.pairingToken.value = "";
  ui.pairingToken.placeholder = "로컬 QA 자동 인증 사용 중";
}

async function api(path, options = {}) {
  const response = await fetch(`${normalizedBaseUrl()}${path}`, {
    ...options,
    headers: {
      ...authHeaders(),
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return body;
}

function showToast(message) {
  ui.toast.textContent = message;
  ui.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => ui.toast.classList.remove("visible"), 2600);
}

function setConnection(connected, label = connected ? "연결됨" : "연결 안 됨") {
  state.connected = connected;
  ui.connectionBadge.textContent = label;
  ui.connectionBadge.className = `badge ${connected ? "online" : "offline"}`;
  ui.connectButton.textContent = connected ? "연결 해제" : "연결";
  ui.startButton.disabled = !connected;
  ui.stopButton.disabled = !connected || !state.listening;
  ui.interruptButton.disabled = !connected;
  ui.saveVoiceButton.disabled = !connected;
  ui.voiceProfile.disabled = !connected;
}

function setAssistant(value, detail = "") {
  ui.assistantBadge.textContent = assistantLabels[value] || value || "대기";
  ui.assistantBadge.className = `badge ${value === "error" ? "offline" : value ? "online" : "muted"}`;
  ui.statusLine.textContent = detail || assistantLabels[value] || "대기 중입니다.";
}

function addEvent(type, payload = {}) {
  const row = document.createElement("div");
  row.className = "event-row";
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString("ko-KR", { hour12: false });
  const name = document.createElement("span");
  name.textContent = type;
  const detail = document.createElement("code");
  const summary = { ...payload };
  if (summary.data_base64) summary.data_base64 = `<PCM ${summary.duration_ms || "?"}ms>`;
  detail.textContent = JSON.stringify(summary, null, 0);
  row.append(time, name, detail);
  ui.events.prepend(row);
  while (ui.events.children.length > 250) ui.events.lastChild.remove();
}

function clearConversationPlaceholder() {
  ui.conversation.querySelector(".empty-state")?.remove();
}

function addMessage(role, text = "") {
  clearConversationPlaceholder();
  const element = document.createElement("div");
  element.className = `message ${role}`;
  element.textContent = text;
  ui.conversation.appendChild(element);
  ui.conversation.scrollTop = ui.conversation.scrollHeight;
  return element;
}

function send(type, payload, requestId = crypto.randomUUID()) {
  if (state.socket?.readyState !== WebSocket.OPEN) return false;
  const envelope = {
    schema_version: "1.0",
    type,
    session_id: state.sessionId,
    request_id: requestId,
    sequence: state.sequence++,
    timestamp: new Date().toISOString(),
    payload,
  };
  state.socket.send(JSON.stringify(envelope));
  addEvent(`→ ${type}`, payload);
  return true;
}

async function connect() {
  if (state.connected) {
    await disconnect();
    return;
  }
  ui.connectButton.disabled = true;
  setConnection(false, "연결 중");
  try {
    const base = normalizedBaseUrl();
    localStorage.setItem("lva.qa.serverUrl", base);
    if (!ui.pairingToken.value && canUseLocalQaBootstrap()) {
      await bootstrapLocalQa();
    }
    const ticket = await api("/v1/qa/ws-ticket", { method: "POST", body: "{}" });
    const websocketUrl = new URL(
      `/v1/sessions/${state.sessionId}/events`,
      base,
    );
    websocketUrl.protocol = websocketUrl.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(
      websocketUrl,
      ["lva.qa.v1", `lva.ticket.${ticket.ticket}`],
    );
    state.socket = socket;
    socket.addEventListener("open", async () => {
      setConnection(true);
      setAssistant("idle", "연결됨. 통화를 시작할 수 있습니다.");
      ui.connectButton.disabled = false;
      addEvent("socket.open", { session_id: state.sessionId });
      await Promise.allSettled([refreshDiagnostics(), loadVoiceSettings()]);
    });
    socket.addEventListener("message", (event) => {
      try {
        handleServerEvent(JSON.parse(event.data));
      } catch (error) {
        addEvent("portal.decode_error", { message: String(error) });
      }
    });
    socket.addEventListener("close", async (event) => {
      addEvent("socket.close", { code: event.code, reason: event.reason });
      await stopCapture(false);
      stopPlayback();
      state.socket = null;
      setConnection(false, event.code === 1000 ? "연결 안 됨" : `실패 ${event.code}`);
      ui.connectButton.disabled = false;
      setAssistant("error", event.reason || "WebSocket 연결이 종료됐습니다.");
    });
    socket.addEventListener("error", () => {
      setAssistant("error", "WebSocket 연결에 실패했습니다.");
    });
  } catch (error) {
    setConnection(false, "연결 실패");
    ui.connectButton.disabled = false;
    setAssistant("error", error.message);
    showToast(error.message);
  }
}

async function disconnect() {
  state.manuallyStopped = true;
  await stopCapture(false);
  stopPlayback();
  if (state.socket) {
    state.socket.close(1000, "user disconnect");
  }
}

async function ensureAudioContext() {
  if (!state.audioContext || state.audioContext.state === "closed") {
    state.audioContext = new AudioContext({ latencyHint: "interactive" });
    await state.audioContext.audioWorklet.addModule("/qa/pcm-worklet.js");
  }
  if (state.audioContext.state === "suspended") await state.audioContext.resume();
}

function downsampleTo16k(input, sourceRate) {
  if (sourceRate === 16000) return input;
  const ratio = sourceRate / 16000;
  const length = Math.floor(input.length / ratio);
  const output = new Float32Array(length);
  for (let index = 0; index < length; index++) {
    const start = Math.floor(index * ratio);
    const end = Math.min(input.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    for (let sample = start; sample < end; sample++) sum += input[sample];
    output[index] = sum / Math.max(1, end - start);
  }
  return output;
}

function floatToPcm16(samples) {
  const pcm = new Int16Array(samples.length);
  let peak = 0;
  for (let index = 0; index < samples.length; index++) {
    const value = Math.max(-1, Math.min(1, samples[index]));
    peak = Math.max(peak, Math.abs(value));
    pcm[index] = value < 0 ? value * 32768 : value * 32767;
  }
  ui.micMeter.style.width = `${Math.min(100, peak * 240)}%`;
  return new Uint8Array(pcm.buffer);
}

function bytesToBase64(bytes) {
  let binary = "";
  const stride = 0x8000;
  for (let index = 0; index < bytes.length; index += stride) {
    binary += String.fromCharCode(...bytes.subarray(index, index + stride));
  }
  return btoa(binary);
}

async function startListening() {
  if (!state.connected || state.listening) return;
  state.manuallyStopped = false;
  stopPlayback();
  try {
    await ensureAudioContext();
    const media = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    const streamId = crypto.randomUUID();
    const requestId = crypto.randomUUID();
    if (!send("audio.input.start", {
      audio_stream_id: streamId,
      encoding: "pcm_s16le",
      sample_rate_hz: 16000,
      channels: 1,
    }, requestId)) {
      media.getTracks().forEach((track) => track.stop());
      throw new Error("오디오 시작 이벤트를 보낼 수 없습니다.");
    }
    state.inputStreamId = streamId;
    state.currentRequestId = requestId;
    state.inputChunkIndex = 0;
    state.mediaStream = media;
    state.turn = { startedAt: performance.now() };
    const source = state.audioContext.createMediaStreamSource(media);
    const worklet = new AudioWorkletNode(state.audioContext, "lva-pcm-capture");
    const silent = state.audioContext.createGain();
    silent.gain.value = 0;
    source.connect(worklet).connect(silent).connect(state.audioContext.destination);
    worklet.port.onmessage = ({ data }) => {
      if (!state.listening || !state.inputStreamId) return;
      const downsampled = downsampleTo16k(
        new Float32Array(data),
        state.audioContext.sampleRate,
      );
      const bytes = floatToPcm16(downsampled);
      const durationMs = Math.max(1, Math.round(downsampled.length / 16));
      send("audio.input.chunk", {
        audio_stream_id: state.inputStreamId,
        chunk_index: state.inputChunkIndex++,
        encoding: "pcm_s16le",
        duration_ms: durationMs,
        data_base64: bytesToBase64(bytes),
      }, requestId);
    };
    state.captureSource = source;
    state.captureNode = worklet;
    state.captureGain = silent;
    state.listening = true;
    ui.startButton.classList.add("active");
    ui.startButton.textContent = " 듣는 중";
    ui.startButton.prepend(Object.assign(document.createElement("span"), { className: "call-dot" }));
    ui.stopButton.disabled = false;
    setAssistant("listening");
  } catch (error) {
    await stopCapture(false);
    showToast(error.message);
    setAssistant("error", error.message);
  }
}

async function stopCapture(sendEnd = true, reason = "client_stop") {
  const streamId = state.inputStreamId;
  const requestId = state.currentRequestId;
  state.listening = false;
  state.inputStreamId = null;
  state.captureNode?.disconnect();
  state.captureSource?.disconnect();
  state.captureGain?.disconnect();
  state.mediaStream?.getTracks().forEach((track) => track.stop());
  state.captureNode = null;
  state.captureSource = null;
  state.captureGain = null;
  state.mediaStream = null;
  ui.micMeter.style.width = "0";
  ui.startButton.classList.remove("active");
  ui.startButton.innerHTML = '<span class="call-dot"></span>대화 시작';
  ui.stopButton.disabled = true;
  if (sendEnd && streamId && requestId) {
    state.turn.audioEndedAt = performance.now();
    send("audio.input.end", { audio_stream_id: streamId, reason }, requestId);
  }
}

function stopPlayback() {
  state.playbackGeneration += 1;
  state.playbackChain = Promise.resolve();
  clearTimeout(state.playbackEndTimer);
  for (const source of state.playbackSources) {
    try { source.stop(); } catch {}
  }
  state.playbackSources.clear();
  state.nextPlaybackTime = state.audioContext?.currentTime || 0;
}

function decodePcm16(encoded) {
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
  return new Int16Array(bytes.buffer);
}

async function scheduleAudio(payload, generation) {
  await ensureAudioContext();
  if (generation !== state.playbackGeneration) return;
  const pcm = decodePcm16(payload.data_base64);
  const buffer = state.audioContext.createBuffer(
    payload.channels,
    Math.floor(pcm.length / payload.channels),
    payload.sample_rate_hz,
  );
  for (let channel = 0; channel < payload.channels; channel++) {
    const target = buffer.getChannelData(channel);
    for (let index = 0; index < target.length; index++) {
      target[index] = pcm[index * payload.channels + channel] / 32768;
    }
  }
  const now = state.audioContext.currentTime;
  if (!state.turn.firstAudioAt) {
    state.turn.firstAudioAt = performance.now();
    updateMetric("tts", state.turn.firstAudioAt - (state.turn.firstTextAt || state.turn.transcriptAt || state.turn.audioEndedAt));
  }
  let startAt = Math.max(now + 0.025, state.nextPlaybackTime);
  if (state.nextPlaybackTime > 0 && now > state.nextPlaybackTime + 0.02) {
    const gap = (now - state.nextPlaybackTime) * 1000;
    state.turn.maxGapMs = Math.max(state.turn.maxGapMs || 0, gap);
    updateMetric("gap", state.turn.maxGapMs);
    addEvent("playback.underrun", { gap_ms: Math.round(gap) });
    startAt = now + 0.025;
  }
  const source = state.audioContext.createBufferSource();
  source.buffer = buffer;
  source.playbackRate.value = Number(ui.playbackRate.value);
  source.connect(state.audioContext.destination);
  source.onended = () => state.playbackSources.delete(source);
  source.start(startAt);
  state.playbackSources.add(source);
  state.nextPlaybackTime = startAt + buffer.duration / source.playbackRate.value;
}

function enqueueAudio(payload) {
  const generation = state.playbackGeneration;
  state.playbackChain = state.playbackChain
    .then(() => scheduleAudio(payload, generation))
    .catch((error) => {
      if (generation !== state.playbackGeneration) return;
      setAssistant("error", `오디오 재생 실패: ${error.message}`);
      addEvent("playback.error", { message: error.message });
    });
}

function finishPlayback() {
  const generation = state.playbackGeneration;
  state.playbackChain = state.playbackChain.then(() => {
    if (generation !== state.playbackGeneration) return;
    const waitMs = Math.max(
      0,
      ((state.nextPlaybackTime || 0) - (state.audioContext?.currentTime || 0)) * 1000,
    );
    clearTimeout(state.playbackEndTimer);
    state.playbackEndTimer = setTimeout(() => {
      if (
        generation === state.playbackGeneration
        && ui.autoContinue.checked
        && !state.manuallyStopped
        && state.connected
      ) {
        startListening();
      }
    }, waitMs + 220);
  });
}

function updateMetric(name, value) {
  if (!Number.isFinite(value)) return;
  state.metrics[name] = value;
  const formatted = `${Math.round(value)} ms`;
  if (name === "stt") ui.sttMetric.textContent = formatted;
  if (name === "llm") ui.llmMetric.textContent = formatted;
  if (name === "tts") ui.ttsMetric.textContent = formatted;
  if (name === "gap") ui.gapMetric.textContent = formatted;
}

function resetMetrics() {
  state.metrics = {};
  for (const element of [ui.sttMetric, ui.llmMetric, ui.ttsMetric, ui.gapMetric]) element.textContent = "—";
}

function showApproval(payload) {
  state.pendingApproval = payload;
  ui.approvalTitle.textContent = `${payload.tool_name} 실행 승인`;
  ui.riskBadge.textContent = `LEVEL ${payload.risk_level}`;
  ui.approvalDetails.replaceChildren();
  for (const [label, value] of [
    ["대상", payload.target],
    ["예상 변경", (payload.expected_changes || []).join(", ") || "없음"],
    ["영향 범위", payload.impact_scope],
    ["Rollback", payload.rollback],
    ["만료", payload.expires_at],
  ]) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    ui.approvalDetails.append(dt, dd);
  }
  ui.approvalArguments.textContent = JSON.stringify(payload.normalized_arguments, null, 2);
  ui.approvalCard.classList.remove("hidden");
}

function respondApproval(approved) {
  const approval = state.pendingApproval;
  if (!approval) return;
  send("tool.approval.response", {
    approval_id: approval.approval_id,
    decision: approved ? "approve" : "reject",
    arguments_digest: approval.arguments_digest,
  }, state.currentRequestId || crypto.randomUUID());
  state.pendingApproval = null;
  ui.approvalCard.classList.add("hidden");
}

function handleServerEvent(envelope) {
  const { type, payload } = envelope;
  addEvent(`← ${type}`, payload);
  if (type === "assistant.state") {
    if (payload.state === "connecting" && payload.detail === "authenticated") {
      setAssistant("idle", "연결됨. 통화를 시작할 수 있습니다.");
    } else {
      setAssistant(payload.state, payload.detail || "");
    }
    if (payload.state === "recognizing" && payload.detail === "vad_end_detected" && state.listening) {
      stopCapture(true, "vad_end");
    }
  } else if (type === "transcript.user.final") {
    state.turn.transcriptAt = performance.now();
    updateMetric("stt", state.turn.transcriptAt - state.turn.audioEndedAt);
    addMessage("user", payload.text);
    state.assistantMessage = null;
  } else if (type === "assistant.text.delta") {
    if (!state.turn.firstTextAt) {
      state.turn.firstTextAt = performance.now();
      updateMetric("llm", state.turn.firstTextAt - state.turn.transcriptAt);
    }
    if (!state.assistantMessage) state.assistantMessage = addMessage("assistant");
    state.assistantMessage.textContent += payload.text;
    ui.conversation.scrollTop = ui.conversation.scrollHeight;
  } else if (type === "assistant.text.final") {
    if (!state.assistantMessage) state.assistantMessage = addMessage("assistant", payload.text);
  } else if (type === "audio.output.chunk") {
    enqueueAudio(payload);
  } else if (type === "audio.output.end") {
    finishPlayback();
  } else if (type === "tool.approval.required") {
    showApproval(payload);
  } else if (type === "error") {
    setAssistant("error", `${payload.error_code}: ${payload.message}`);
    showToast(payload.message);
  }
}

async function refreshDiagnostics() {
  const values = ui.diagnostics.querySelectorAll("strong");
  values.forEach((value) => { value.textContent = "확인 중"; });
  const runtimeStatus = api("/v1/qa/runtime-status");
  const probes = [
    fetch(`${normalizedBaseUrl()}/health`).then((response) => response.json()).then(() => "정상"),
    runtimeStatus.then((body) => (
      body.runtime.state === "ready"
        ? `${body.runtime.model_id} · MTP ${body.runtime.mtp_mode}`
        : "런타임 사용 불가"
    )),
    runtimeStatus.then((body) => (
      Object.entries(body.workers)
        .map(([name, ready]) => `${name.toUpperCase()} ${ready ? "✓" : "×"}`)
        .join(" · ")
    )),
    api("/v1/status/agents").then((body) => `${body.agents.length} adapter`),
  ];
  const results = await Promise.allSettled(probes);
  results.forEach((result, index) => {
    values[index].textContent = result.status === "fulfilled" ? result.value : "사용 불가";
  });
}

async function loadVoiceSettings() {
  const body = await api("/v1/voice/profiles");
  ui.voiceProfile.replaceChildren();
  for (const profile of body.profiles) {
    const option = document.createElement("option");
    option.value = profile.profile_id;
    option.textContent = `${profile.name} · ${profile.style}`;
    ui.voiceProfile.appendChild(option);
  }
  const settings = body.settings;
  ui.voiceProfile.value = settings.profile_id;
  ui.playbackRate.value = settings.playback_rate;
  ui.exaggeration.value = settings.exaggeration;
  ui.cfgWeight.value = settings.cfg_weight;
  ui.temperature.value = settings.temperature;
  syncSliderLabels();
}

async function saveVoiceSettings() {
  try {
    const body = await api("/v1/voice/settings", {
      method: "PUT",
      body: JSON.stringify({
        profile_id: ui.voiceProfile.value,
        playback_rate: Number(ui.playbackRate.value),
        exaggeration: Number(ui.exaggeration.value),
        cfg_weight: Number(ui.cfgWeight.value),
        temperature: Number(ui.temperature.value),
      }),
    });
    showToast(`음성 설정 저장됨 · ${body.settings.profile_id}`);
  } catch (error) {
    showToast(error.message);
  }
}

function syncSliderLabels() {
  ui.rateValue.textContent = `${Number(ui.playbackRate.value).toFixed(2)}×`;
  ui.emotionValue.textContent = Number(ui.exaggeration.value).toFixed(2);
  ui.cfgValue.textContent = Number(ui.cfgWeight.value).toFixed(2);
  ui.temperatureValue.textContent = Number(ui.temperature.value).toFixed(2);
}

function interrupt() {
  state.manuallyStopped = true;
  stopCapture(false);
  stopPlayback();
  if (state.currentRequestId) {
    send("operation.cancel.requested", {
      target_kind: "assistant_response",
      target_id: state.currentRequestId,
      reason: "user_request",
      idempotency_key: crypto.randomUUID(),
    }, state.currentRequestId);
  }
  setAssistant("interrupted");
}

ui.serverUrl.value = localStorage.getItem("lva.qa.serverUrl") || location.origin;
ui.connectButton.addEventListener("click", connect);
ui.diagnoseButton.addEventListener("click", () => refreshDiagnostics().catch((error) => showToast(error.message)));
ui.startButton.addEventListener("click", startListening);
ui.stopButton.addEventListener("click", () => {
  state.manuallyStopped = true;
  stopCapture(true, "client_stop");
});
ui.interruptButton.addEventListener("click", interrupt);
ui.resetMetricsButton.addEventListener("click", resetMetrics);
ui.clearEventsButton.addEventListener("click", () => ui.events.replaceChildren());
ui.approveButton.addEventListener("click", () => respondApproval(true));
ui.rejectButton.addEventListener("click", () => respondApproval(false));
ui.saveVoiceButton.addEventListener("click", saveVoiceSettings);
for (const slider of [ui.playbackRate, ui.exaggeration, ui.cfgWeight, ui.temperature]) {
  slider.addEventListener("input", syncSliderLabels);
}
window.addEventListener("beforeunload", () => {
  state.socket?.close(1000, "page closing");
  state.mediaStream?.getTracks().forEach((track) => track.stop());
});
syncSliderLabels();
setConnection(false);
if (canUseLocalQaBootstrap()) {
  connect();
}
