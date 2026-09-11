

export interface AgentSourceRef {
  type?: string;
  questionId?: number | string;
  documentId?: number | string;
  chunkId?: string;
  title?: string;
  question?: string;
  heading?: string;
  snippet?: string;
  source?: string;
  version?: number | string;
  retrieval?: string;
  url?: string;
}

export interface AgentHistoryMessage {
  messageId: number;
  userMessage?: string;
  imageAssetId?: string;
  imageSnapshot?: Record<string, unknown>;
  selectedVisualSubject?: Record<string, unknown>;
  assistantMessage: string;
  status: number;
  bizType?: string;
  bizData?: string | null;
  sendTime?: string;
  sourceRefs?: AgentSourceRef[];
  messageType?: string;
  eventType?: string;
  schemaVersion?: number;
  runId?: string;
  requestId?: string;
  episodeId?: string;
  eventId?: string;
  seq?: number;
  terminalState?: string;
  deliveryState?: string;
  replayCursor?: string;
  replaySupported?: boolean;
}

type StreamAccumulator = {
  chunks: Map<number, string>;
  seenEvents: Set<string>;
  seenSequences: Set<number>;
  terminal: boolean;
};

// Keep ordering/dedupe state outside the public history shape.  This avoids
// leaking reducer bookkeeping into Vue templates or persisted history rows.
// Key by the durable message ID rather than object identity: history merges
// intentionally clone rows while a live stream may still be arriving.
const streamAccumulators = new Map<number, StreamAccumulator>();
const MAX_STREAM_ACCUMULATORS = 512;

const streamAccumulatorFor = (message: AgentHistoryMessage): StreamAccumulator => {
  let accumulator = streamAccumulators.get(message.messageId);
  if (!accumulator) {
    accumulator = {
      chunks: new Map(),
      seenEvents: new Set(),
      seenSequences: new Set(),
      terminal: false
    };
    if (streamAccumulators.size >= MAX_STREAM_ACCUMULATORS) {
      const oldest = streamAccumulators.keys().next().value;
      if (oldest != null) streamAccumulators.delete(oldest);
    }
    streamAccumulators.set(message.messageId, accumulator);
  }
  return accumulator;
};

const parsePositiveSequence = (value: unknown): number | undefined => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
};

const parseBoolean = (value: unknown): boolean | undefined => {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'true' || normalized === '1') return true;
    if (normalized === 'false' || normalized === '0') return false;
  }
  return undefined;
};

const TERMINAL_STATES = new Set([
  'SUCCEEDED',
  'FAILED',
  'CANCELLED',
  'INTERRUPTED',
  'DEGRADED',
  'PARTIAL_SUCCESS',
  'CLARIFICATION_REQUIRED',
  'INCONCLUSIVE',
  'MANUAL_REVIEW'
]);

const hasTerminalState = (value: unknown) =>
  TERMINAL_STATES.has(String(value || '').trim().toUpperCase());

const copyStreamEnvelope = (
  target: AgentHistoryMessage,
  payload: AgentStreamPayload | Record<string, unknown>
) => {
  const source = payload as Record<string, unknown>;
  const schemaVersion = Number(source.schemaVersion ?? source.schema_version);
  const sequence = parsePositiveSequence(source.seq ?? source.sequence);
  const advancesCursor = sequence == null || sequence >= Number(target.seq || 0);
  if (Number.isFinite(schemaVersion) && schemaVersion > 0) target.schemaVersion = schemaVersion;
  if (source.runId != null || source.run_id != null) {
    target.runId = String(source.runId ?? source.run_id);
  }
  if (source.requestId != null || source.request_id != null) {
    target.requestId = String(source.requestId ?? source.request_id);
  }
  if (source.episodeId != null || source.episode_id != null) {
    target.episodeId = String(source.episodeId ?? source.episode_id);
  }
  if (advancesCursor && (source.eventId != null || source.event_id != null)) {
    target.eventId = String(source.eventId ?? source.event_id);
  }
  if (sequence != null && advancesCursor) target.seq = sequence;
  if (source.terminalState != null || source.terminal_state != null) {
    target.terminalState = String(source.terminalState ?? source.terminal_state);
  }
  if (source.replaySupported != null || source.replay_supported != null) {
    const supported = parseBoolean(source.replaySupported ?? source.replay_supported);
    if (supported != null) target.replaySupported = supported;
  }
  if (advancesCursor && (source.replayCursor != null || source.replay_cursor != null)) {
    target.replayCursor = String(source.replayCursor ?? source.replay_cursor);
  }
};

const pickField = (raw: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) {
    const val = raw[key];
    if (val != null && val !== '') return val;
  }
  return undefined;
};

export const normalizeSourceRefs = (raw: unknown): AgentSourceRef[] => {
  const value = raw && !Array.isArray(raw) && typeof raw === 'object'
    ? (raw as Record<string, unknown>).sources
    : raw;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is AgentSourceRef => !!item && typeof item === 'object');
};

export const extractHistoryPage = (res: unknown) => {
  if (Array.isArray(res)) {
    return { list: res, pageNo: 1, pageTotal: 1, totalCount: res.length };
  }

  let page: Record<string, unknown> | null = null;
  if (res && typeof res === 'object') {
    page = res as Record<string, unknown>;
    if (page.data && typeof page.data === 'object' && !Array.isArray(page.list)) {
      page = page.data as Record<string, unknown>;
    }
  }

  if (!page) {
    return { list: [], pageNo: 1, pageTotal: 1, totalCount: 0 };
  }

  const list = Array.isArray(page.list)
    ? page.list
    : Array.isArray(page.records)
      ? page.records
      : Array.isArray(page.rows)
        ? page.rows
        : [];

  return {
    list,
    pageNo: Number(page.pageNo) || 1,
    pageTotal: Number(page.pageTotal) || 1,
    totalCount: Number(page.totalCount) || list.length
  };
};

export const normalizeAgentHistoryMessage = (raw: Record<string, unknown>): AgentHistoryMessage => {
  const messageIdRaw = pickField(raw, 'messageId', 'message_id');
  const parsedId = messageIdRaw != null ? Number(messageIdRaw) : 0;
  const assistantRaw = pickField(raw, 'assistantMessage', 'assistant_message');
  const userRaw = pickField(raw, 'userMessage', 'user_message');
  const bizTypeRaw = pickField(raw, 'bizType', 'biz_type');
  const bizDataRaw = pickField(raw, 'bizData', 'biz_data');
  const sendTimeRaw = pickField(raw, 'sendTime', 'send_time');
  const statusRaw = pickField(raw, 'status');
  const sourceRefs = normalizeSourceRefs(pickField(raw, 'sourceRefs', 'source_refs'));
  const rawSourceRefs = pickField(raw, 'sourceRefs', 'source_refs');
  const messageTypeRaw = pickField(raw, 'messageType', 'message_type');
  const eventTypeRaw = pickField(raw, 'eventType', 'event_type');
  const schemaVersionRaw = pickField(raw, 'schemaVersion', 'schema_version');
  const runIdRaw = pickField(raw, 'runId', 'run_id');
  const requestIdRaw = pickField(raw, 'requestId', 'request_id');
  const episodeIdRaw = pickField(raw, 'episodeId', 'episode_id');
  const eventIdRaw = pickField(raw, 'eventId', 'event_id');
  const seqRaw = pickField(raw, 'seq', 'sequence');
  const terminalStateRaw = pickField(raw, 'terminalState', 'terminal_state');
  const deliveryStateRaw = pickField(raw, 'deliveryState', 'delivery_state');
  const replayCursorRaw = pickField(raw, 'replayCursor', 'replay_cursor');
  const replaySupportedRaw = pickField(raw, 'replaySupported', 'replay_supported');
  const inferredPending = statusRaw == null && /^(?:PENDING|QUEUED|DISPATCHING|PROCESSING|RUNNING|RETRYING|IDEMPOTENCY_IN_PROGRESS)$/i.test(
    String(deliveryStateRaw || '')
  );
  const imageAssetIdRaw = pickField(raw, 'imageAssetId', 'image_asset_id');
  const imageSnapshotRaw = pickField(raw, 'imageSnapshot', 'image_snapshot_json');
  const selectedVisualSubjectRaw = pickField(
    raw,
    'selectedVisualSubject',
    'selected_visual_subject_json'
  );

  return {
    messageId: Number.isFinite(parsedId) && parsedId > 0 ? parsedId : 0,
    userMessage: userRaw != null ? String(userRaw) : undefined,
    imageAssetId: imageAssetIdRaw != null ? String(imageAssetIdRaw) : undefined,
    imageSnapshot: imageSnapshotRaw && typeof imageSnapshotRaw === 'object'
      ? imageSnapshotRaw as Record<string, unknown>
      : undefined,
    selectedVisualSubject: selectedVisualSubjectRaw && typeof selectedVisualSubjectRaw === 'object'
      ? selectedVisualSubjectRaw as Record<string, unknown>
      : undefined,
    assistantMessage: assistantRaw != null ? String(assistantRaw) : '',
    status: statusRaw != null ? Number(statusRaw) : inferredPending ? 1 : 2,
    bizType: bizTypeRaw != null ? String(bizTypeRaw) : undefined,
    bizData: bizDataRaw != null ? String(bizDataRaw) : null,
    sendTime: sendTimeRaw != null ? String(sendTimeRaw) : undefined,
    sourceRefs,
    messageType: messageTypeRaw != null ? String(messageTypeRaw) : undefined,
    eventType: eventTypeRaw != null ? String(eventTypeRaw) : undefined,
    schemaVersion: schemaVersionRaw != null ? Number(schemaVersionRaw) : undefined,
    runId: runIdRaw != null ? String(runIdRaw) : undefined,
    requestId: requestIdRaw != null ? String(requestIdRaw) : undefined,
    episodeId: episodeIdRaw != null ? String(episodeIdRaw) : undefined,
    eventId: eventIdRaw != null ? String(eventIdRaw) : undefined,
    seq: parsePositiveSequence(seqRaw),
    terminalState: terminalStateRaw != null
      ? String(terminalStateRaw)
      : rawSourceRefs && typeof rawSourceRefs === 'object' && !Array.isArray(rawSourceRefs)
        ? String((rawSourceRefs as Record<string, unknown>).terminalState || '') || undefined
        : undefined,
    deliveryState: deliveryStateRaw != null ? String(deliveryStateRaw) : undefined,
    replayCursor: replayCursorRaw != null ? String(replayCursorRaw) : undefined,
    replaySupported: replaySupportedRaw != null
      ? parseBoolean(replaySupportedRaw)
      : undefined
  };
};

export interface AgentStreamPayload {
  messageId?: number | string;
  userMessage?: string;
  imageAssetId?: string;
  imageSnapshot?: Record<string, unknown>;
  selectedVisualSubject?: Record<string, unknown>;
  assistantMessage?: string;
  bizType?: string;
  bizData?: string | null;
  outPutType?: number;
  sendTime?: string;
  sourceRefs?: AgentSourceRef[] | { sources?: AgentSourceRef[] };
  messageType?: string;
  eventType?: string;
  schemaVersion?: number | string;
  runId?: string;
  requestId?: string;
  episodeId?: string;
  eventId?: string;
  seq?: number | string;
  terminalState?: string;
  deliveryState?: string;
  replayCursor?: string;
  replaySupported?: boolean;
}

export interface AgentUpsertResult {
  message: AgentHistoryMessage;
  created: boolean;
  terminal: boolean;
}

export const upsertAgentStreamMessage = (
  list: AgentHistoryMessage[],
  payload: AgentStreamPayload
): AgentUpsertResult | null => {
  const parsedId = Number(payload.messageId);
  if (!Number.isFinite(parsedId) || parsedId <= 0) return null;

  const outputType = Number(payload.outPutType ?? 0);
  const terminalState = String(payload.terminalState || '').toUpperCase();
  const terminal =
    outputType === 1 ||
    outputType === 2 ||
    [
      'SUCCEEDED',
      'FAILED',
      'CANCELLED',
      'INTERRUPTED',
      'DEGRADED',
      'PARTIAL_SUCCESS',
      'CLARIFICATION_REQUIRED',
      'INCONCLUSIVE',
      'MANUAL_REVIEW'
    ].includes(
      terminalState
    );
  let message = list.find((item) => String(item.messageId) === String(parsedId));
  const created = !message;
  if (!message) {
    message = {
      messageId: parsedId,
      assistantMessage: '',
      status: terminal ? 2 : 1
    };
    list.push(message);
  }

  const accumulator = streamAccumulatorFor(message);
  const sequence = parsePositiveSequence(payload.seq);
  const eventId = payload.eventId ? String(payload.eventId) : undefined;
  // A terminal history row is the reconciliation source of truth.  Ignore
  // any late pub/sub frame, including legacy frames without envelope fields.
  if (accumulator.terminal) {
    return { message, created: false, terminal: false };
  }
  const hasEnvelopeOrdering = sequence != null || !!eventId;
  if (hasEnvelopeOrdering) {
    if (eventId && accumulator.seenEvents.has(eventId)) {
      return { message, created: false, terminal: false };
    }
    if (eventId) accumulator.seenEvents.add(eventId);
    if (sequence != null) {
      // A sequence is unique within a run.  This also handles duplicate
      // delivery from Redis when an event ID was not preserved by a proxy.
      if (accumulator.seenSequences.has(sequence)) {
        return { message, created: false, terminal: false };
      }
      accumulator.seenSequences.add(sequence);
    }
  }

  copyStreamEnvelope(message, payload);

  if (payload.userMessage != null && payload.userMessage !== '') {
    message.userMessage = String(payload.userMessage);
  }
  if (payload.imageAssetId) message.imageAssetId = String(payload.imageAssetId);
  if (payload.imageSnapshot && typeof payload.imageSnapshot === 'object') {
    message.imageSnapshot = payload.imageSnapshot;
  }
  if (payload.selectedVisualSubject && typeof payload.selectedVisualSubject === 'object') {
    message.selectedVisualSubject = payload.selectedVisualSubject;
  }
  if (payload.bizType) message.bizType = payload.bizType;
  if (payload.bizData != null) message.bizData = payload.bizData;
  if (payload.sendTime) message.sendTime = payload.sendTime;
  if (payload.messageType) message.messageType = payload.messageType;
  if (payload.eventType) message.eventType = payload.eventType;
  if (payload.replaySupported != null) message.replaySupported = payload.replaySupported;
  if (payload.deliveryState) message.deliveryState = payload.deliveryState;

  const refs = normalizeSourceRefs(payload.sourceRefs);
  if (refs.length || payload.sourceRefs != null) message.sourceRefs = refs;

  if (outputType === 2 || terminalState === 'FAILED') {
    message.assistantMessage = payload.assistantMessage || '服务器返回错误，请联系管理员';
    message.status = 2;
    accumulator.terminal = true;
  } else if (terminal) {
    if (payload.assistantMessage != null && payload.assistantMessage.trim() !== '') {
      // A terminal frame is authoritative and may contain the complete
      // response rather than the individual deltas.
      message.assistantMessage = payload.assistantMessage;
    }
    message.status = 2;
    accumulator.terminal = true;
  } else if (message.status === 1) {
    if (sequence != null) {
      accumulator.chunks.set(sequence, payload.assistantMessage || '');
      message.assistantMessage = [...accumulator.chunks.entries()]
        .sort(([left], [right]) => left - right)
        .map(([, chunk]) => chunk)
        .join('');
    } else {
      message.assistantMessage += payload.assistantMessage || '';
    }
  }

  return { message, created, terminal };
};

export const upsertAgentHttpMessage = (
  list: AgentHistoryMessage[],
  raw: Record<string, unknown>
): AgentHistoryMessage | null => {
  const incoming = normalizeAgentHistoryMessage(raw);
  if (!incoming.messageId) return null;
  const existing = list.find((item) => item.messageId === incoming.messageId);
  if (!existing) {
    if (incoming.status === 1 && hasTerminalState(incoming.terminalState)) {
      incoming.status = 2;
    }
    list.push(incoming);
    if (incoming.status !== 1 || hasTerminalState(incoming.terminalState)) {
      streamAccumulatorFor(incoming).terminal = true;
    }
    return incoming;
  }
  const accumulator = streamAccumulatorFor(existing);
  const alreadyTerminal = accumulator.terminal;
  const wasStreaming = Number(existing.status) === 1;
  if (incoming.userMessage) existing.userMessage = incoming.userMessage;
  if (incoming.imageAssetId) existing.imageAssetId = incoming.imageAssetId;
  if (incoming.imageSnapshot) existing.imageSnapshot = incoming.imageSnapshot;
  if (incoming.selectedVisualSubject) existing.selectedVisualSubject = incoming.selectedVisualSubject;
  if (incoming.bizType) existing.bizType = incoming.bizType;
  if (incoming.bizData != null) existing.bizData = incoming.bizData;
  if (incoming.sendTime) existing.sendTime = incoming.sendTime;
  if (incoming.sourceRefs?.length) existing.sourceRefs = incoming.sourceRefs;
  if (incoming.schemaVersion != null) existing.schemaVersion = incoming.schemaVersion;
  if (incoming.runId) existing.runId = incoming.runId;
  if (incoming.requestId) existing.requestId = incoming.requestId;
  if (incoming.episodeId) existing.episodeId = incoming.episodeId;
  if (incoming.eventId) existing.eventId = incoming.eventId;
  if (incoming.seq != null) existing.seq = incoming.seq;
  if (incoming.terminalState) existing.terminalState = incoming.terminalState;
  if (incoming.deliveryState) existing.deliveryState = incoming.deliveryState;
  if (incoming.replayCursor) existing.replayCursor = incoming.replayCursor;
  if (incoming.eventType) existing.eventType = incoming.eventType;
  if (incoming.replaySupported != null) existing.replaySupported = incoming.replaySupported;
  // A delayed HTTP enqueue response may still carry status=1 after a terminal
  // WebSocket frame. Never downgrade that authoritative terminal projection.
  if (!alreadyTerminal) {
    existing.status = hasTerminalState(incoming.terminalState) && incoming.status === 1
      ? 2
      : incoming.status;
  }
  if (!alreadyTerminal && (incoming.status !== 1 || hasTerminalState(incoming.terminalState))) {
    accumulator.terminal = true;
  }
  if (wasStreaming && incoming.assistantMessage) {
    existing.assistantMessage = incoming.assistantMessage;
  }
  return existing;
};

export const sortHistoryMessages = (list: AgentHistoryMessage[]) =>
  [...list].sort((a, b) => a.messageId - b.messageId);

export const mergeHistoryMessages = (
  existing: AgentHistoryMessage[],
  incoming: AgentHistoryMessage[]
) => {
  const map = new Map<number, AgentHistoryMessage>();
  existing.forEach((item) => {
    if (item.messageId) map.set(item.messageId, item);
  });
  incoming.forEach((item) => {
    if (!item.messageId) return;
    const previous = map.get(item.messageId);
    map.set(item.messageId, previous ? { ...previous, ...item } : item);
  });
  return sortHistoryMessages([...map.values()]);
};

// ---------------------------------------------------------------------------
// Recommendation card actionability (black-box attribution hygiene)
// ---------------------------------------------------------------------------
// Only the recommendation cards rendered by the *newest* assistant reply may
// stay interactive.  An older card must not keep producing CLICK/order
// touchpoints bound to a superseded requestId/runId, otherwise a later task
// would silently reuse the previous recommendation's attribution.

const PRODUCT_RESPONSE_BIZ_TYPES = new Set([
  'product_search',
  'product_search.txt',
  'BROWSE_RECOMMEND',
  'visual_product_search',
  'shopping_decision_v2'
]);

const hasProductIdentity = (item: unknown): item is Record<string, unknown> => {
  const candidate = item as Record<string, unknown> | null;
  return !!candidate && typeof candidate === 'object'
    && !!(candidate.productId || candidate.product_id)
    && !!(candidate.productName || candidate.product_name);
};

const parseJsonPayloadList = (raw: string | null | undefined): unknown[] | null => {
  if (!raw || typeof raw !== 'string') return null;
  const text = raw.trim();
  if (!text.startsWith('[') && !text.startsWith('{')) return null;
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) return parsed;
    if (parsed && Array.isArray((parsed as { list?: unknown }).list)) {
      return (parsed as { list: unknown[] }).list;
    }
    return null;
  } catch {
    return null;
  }
};

/**
 * The recommendation products rendered by an assistant message, or null when
 * the message does not carry an actionable product card.  Streaming (status 1)
 * replies are never actionable: their payload may still be incomplete.
 * Mirrors the renderer rules in AgentChatItem so the thread-level gating in
 * AgentChatList and the bubble-level rendering can never disagree.
 */
export function extractRecommendationProducts(
  message: AgentHistoryMessage | null | undefined
): Record<string, unknown>[] | null {
  if (!message || Number(message.status) === 1) return null;
  const raw = message.assistantMessage;
  if (!raw || typeof raw !== 'string') return null;

  // Wrapped PRODUCT_SEARCH_RESULT payload: { type, intro, products: [...] }.
  const text = raw.trim();
  if (text.startsWith('{')) {
    try {
      const parsed = JSON.parse(text);
      if (parsed?.type === 'PRODUCT_SEARCH_RESULT' && Array.isArray(parsed.products)) {
        const usable = (parsed.products as unknown[]).filter(hasProductIdentity);
        return usable.length ? (usable as Record<string, unknown>[]) : null;
      }
    } catch {
      // Fall through to the generic list parser below.
    }
  }

  const parsed = parseJsonPayloadList(raw);
  if (!parsed?.length) return null;
  const usable = parsed.filter(hasProductIdentity);
  if (!usable.length) return null;
  if (PRODUCT_RESPONSE_BIZ_TYPES.has(String(message.bizType || ''))) {
    return usable as Record<string, unknown>[];
  }
  // Generic assistant list without a product biz marker is treated as a
  // product card only when the first entry carries a full product identity.
  const first = usable[0] as Record<string, unknown>;
  if (first.productId && first.productName) return usable as Record<string, unknown>[];
  return null;
}

const hasComparisonRecommendation = (message: AgentHistoryMessage): boolean => {
  if (Number(message.status) === 1) return false;
  const raw = message.assistantMessage;
  if (!raw || typeof raw !== 'string' || !raw.trim().startsWith('{')) return false;
  try {
    const parsed = JSON.parse(raw.trim());
    return parsed?.type === 'PRODUCT_COMPARISON'
      && Array.isArray(parsed.products)
      && parsed.products.some(
        (item: unknown) => !!item && typeof item === 'object'
          && !!(item as Record<string, unknown>).productId
      );
  } catch {
    return false;
  }
};

/**
 * Message id whose product cards may still be clicked, or null when no card
 * may be operated (no product reply yet, a reply is streaming, or the newest
 * assistant reply no longer carries products — older cards then count as
 * stale and must be inert).
 */
export function latestActionableRecommendationMessageId(
  messages: AgentHistoryMessage[] | undefined | null
): number | null {
  if (!Array.isArray(messages) || !messages.length) return null;
  for (let index = messages.length - 1; index >= 0; index--) {
    const item = messages[index];
    if (!item) continue;
    const status = Number(item.status);
    const hasContent = Boolean((item.assistantMessage || '').trim());
    // Rows without assistant content are normally invisible bookkeeping rows.
    // A row that carries a user prompt, however, is a real new turn; its empty
    // terminal response must still expire older recommendation cards.
    if (status !== 1 && !hasContent) {
      if (String(item.userMessage || '').trim()) return null;
      continue;
    }
    if (status === 1) return null; // A newer reply is still being generated.
    const products = extractRecommendationProducts(item);
    if (products?.length || hasComparisonRecommendation(item)) {
      return Number(item.messageId) || null;
    }
    return null; // Newest reply is final but carries no product card.
  }
  return null;
}
