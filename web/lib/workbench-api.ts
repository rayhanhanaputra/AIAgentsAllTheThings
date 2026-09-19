export type Verdict =
  | 'confirmed_violation'
  | 'no_violation_observed'
  | 'inconclusive';

export interface SessionEvent {
  sequence: number;
  elapsed_ms: number;
  source: string;
  event_type: string;
  data: Record<string, unknown>;
}

export interface SessionResult {
  run_id: string;
  mode: 'workbench' | 'campaign';
  state: 'completed' | 'failed';
  provider: string;
  script: string;
  response_text: string;
  canary: string;
  duration_ms: number;
  events: SessionEvent[];
  analysis: {
    verdict: Verdict;
    canary_matches: number;
    evidence: string[];
    llm_review: {
      status: 'completed' | 'failed';
      model?: string;
      summary?: string;
      error?: string;
    } | null;
  };
  metadata?: {
    target?: {
      id: string;
      name: string;
      environment: TargetEnvironment;
      connector: TargetConnector;
    };
    channel?: {
      adapter: ChannelAdapter;
      message_id: string;
      topic: string;
      body: Record<string, unknown>;
    };
    exchange?: {
      wire_request?: Record<string, unknown>;
      response_metadata?: Record<string, unknown>;
      raw_response?: string;
      actions?: Array<{ name: string; arguments: Record<string, unknown> }>;
    };
    response_mapper?: {
      enabled: boolean;
      status?: 'completed' | 'failed';
      model?: string;
      error?: string;
      fallback?: string;
      used_for_deterministic_evidence?: boolean;
      normalized_metadata?: Record<string, unknown>;
    };
  };
}

export interface IntruderResult {
  case_count: number;
  confirmed_violations: number;
  cases: Array<{
    case_index: number;
    payload: string;
    result: SessionResult;
  }>;
}

export type ChannelAdapter =
  | 'prompt-text'
  | 'json-field'
  | 'sensor-value'
  | 'reading-stream'
  | 'binary-toggle'
  | 'morse-blink'
  | 'voice-transcript'
  | 'qr-code'
  | 'text-in-image'
  | 'agent-note'
  | 'retrieved-doc'
  | 'ble-advert'
  | 'nfc-tag';

export type TargetEnvironment = 'staging' | 'production';
export type TargetConnector =
  | 'http'
  | 'tcp'
  | 'mqtt'
  | 'websocket'
  | 'voice'
  | 'voice-stream'
  | 'optical'
  | 'device-bridge';

export interface MediaAttachment {
  data: string;
  mimeType: string;
  filename: string;
}

export interface EvidenceRules {
  response_markers: string[];
  forbidden_tools: string[];
}

export interface TargetProfileInput {
  name: string;
  environment: TargetEnvironment;
  connector: TargetConnector;
  enabled: boolean;
  endpoint?: string | null;
  method: 'POST' | 'PUT' | 'PATCH';
  headers: Record<string, string>;
  secret_headers: Record<string, string>;
  request_template: string;
  response_path?: string | null;
  actions_path?: string | null;
  mapper_enabled: boolean;
  mapper_endpoint?: string | null;
  mapper_model?: string | null;
  mapper_api_key_env?: string | null;
  mapper_instructions: string;
  mapper_required_keys: string[];
  mapper_timeout_seconds: number;
  response_mapper_enabled: boolean;
  response_mapper_endpoint?: string | null;
  response_mapper_model?: string | null;
  response_mapper_api_key_env?: string | null;
  response_mapper_instructions: string;
  response_mapper_timeout_seconds: number;
  host?: string | null;
  port?: number | null;
  tcp_raw: boolean;
  mqtt_publish_topic?: string | null;
  mqtt_response_topic?: string | null;
  mqtt_qos: 0 | 1;
  mqtt_tls: boolean;
  mqtt_username_env?: string | null;
  mqtt_password_env?: string | null;
  voice_response_audio_path?: string | null;
  voice_response_audio_type:
    | 'audio/wav'
    | 'audio/mpeg'
    | 'audio/ogg'
    | 'audio/webm'
    | 'audio/mp4'
    | 'audio/flac';
  voice_stream_chunk_template: string;
  voice_stream_end_template: string;
  voice_stream_cancel_template: string;
  voice_stream_done_path: string;
  voice_stream_done_value: string;
  voice_stream_chunk_bytes: number;
  voice_stream_max_events: number;
  hardware_kind: 'ble' | 'nfc' | 'gpio' | 'led';
  hardware_operation:
    | 'ble_advertise'
    | 'nfc_emulate'
    | 'gpio_sequence'
    | 'led_sequence';
  hardware_device_id?: string | null;
  hardware_allowed_device_ids: string[];
  hardware_resource?: string | null;
  hardware_allowed_resources: string[];
  hardware_duration_ms: number;
  hardware_stop_endpoint?: string | null;
  hardware_stop_template: string;
  observer_kind: 'none' | 'http' | 'browser';
  observer_url?: string | null;
  observer_selector?: string | null;
  observer_wait_ms: number;
  observer_timeout_seconds: number;
  observer_capture_screenshot: boolean;
  timeout_seconds: number;
  evidence: EvidenceRules;
}

export interface TargetProfile extends TargetProfileInput {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface TargetPreview {
  target: Pick<TargetProfile, 'id' | 'name' | 'environment' | 'connector'>;
  message: {
    msg_id: string;
    topic: string;
    body: Record<string, unknown>;
  };
  wire_request: Record<string, unknown>;
}

const API_URL =
  process.env.NEXT_PUBLIC_AAT_API_URL?.replace(/\/$/, '') ??
  'http://127.0.0.1:8787';

export function resolveArtifactUrl(path: string): string | null {
  if (
    !/^\/api\/runs\/[A-Za-z0-9-]+\/(audio|artifacts\/observation_(before|after))$/.test(
      path,
    )
  )
    return null;
  return `${API_URL}${path}`;
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 35_000);

  try {
    const response = await fetch(`${API_URL}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers:
        body === undefined ? undefined : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Workbench API returned ${response.status}: ${detail}`);
    }
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function mutate<T>(
  path: string,
  method: 'POST' | 'PUT' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers:
      body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Workbench API returned ${response.status}: ${detail}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function checkHealth(): Promise<{ status: string }> {
  return request('/api/health');
}

export function listRuns(): Promise<{ runs: SessionResult[] }> {
  return request('/api/runs');
}

export function listTargets(): Promise<{ targets: TargetProfile[] }> {
  return request('/api/targets');
}

export function createTarget(
  input: TargetProfileInput,
): Promise<TargetProfile> {
  return mutate('/api/targets', 'POST', input);
}

export function updateTarget(
  targetId: string,
  input: TargetProfileInput,
): Promise<TargetProfile> {
  return mutate(`/api/targets/${targetId}`, 'PUT', input);
}

export function deleteTarget(targetId: string): Promise<void> {
  return mutate(`/api/targets/${targetId}`, 'DELETE');
}

export function previewTarget(
  targetId: string,
  adapter: ChannelAdapter,
  fields: Record<string, unknown>,
  audioAttachment?: MediaAttachment | null,
  imageAttachment?: MediaAttachment | null,
): Promise<TargetPreview> {
  return request(`/api/targets/${targetId}/preview`, {
    adapter,
    fields: {
      ...fields,
      ...(audioAttachment
        ? {
            audio_base64: audioAttachment.data,
            audio_mime_type: audioAttachment.mimeType,
            audio_filename: audioAttachment.filename,
          }
        : {}),
      ...(imageAttachment
        ? {
            image_base64: imageAttachment.data,
            image_mime_type: imageAttachment.mimeType,
            image_filename: imageAttachment.filename,
          }
        : {}),
    },
  });
}

export function runTarget(
  targetId: string,
  adapter: ChannelAdapter,
  fields: Record<string, unknown>,
  productionAcknowledged: boolean,
  audioAttachment?: MediaAttachment | null,
  imageAttachment?: MediaAttachment | null,
): Promise<SessionResult> {
  return request('/api/workbench/runs', {
    target_id: targetId,
    adapter,
    fields: {
      ...fields,
      ...(audioAttachment
        ? {
            audio_base64: audioAttachment.data,
            audio_mime_type: audioAttachment.mimeType,
            audio_filename: audioAttachment.filename,
          }
        : {}),
      ...(imageAttachment
        ? {
            image_base64: imageAttachment.data,
            image_mime_type: imageAttachment.mimeType,
            image_filename: imageAttachment.filename,
          }
        : {}),
    },
    production_acknowledged: productionAcknowledged,
  });
}

export function runTargetCampaign(
  targetId: string,
  adapter: ChannelAdapter,
  fieldsTemplate: Record<string, unknown>,
  payloads: string[],
  productionAcknowledged: boolean,
): Promise<IntruderResult> {
  return request('/api/campaigns/runs', {
    target_id: targetId,
    adapter,
    fields_template: fieldsTemplate,
    payloads,
    concurrency: 2,
    production_acknowledged: productionAcknowledged,
  });
}
