'use client';

import Image from 'next/image';
import {
  ArrowDownLeft,
  ArrowUpRight,
  Check,
  CircleAlert,
  Clock3,
  FileText,
  LoaderCircle,
  MessageSquare,
  ScanLine,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { resolveArtifactUrl, type SessionResult } from '@/lib/workbench-api';
import { CopyButton, ErrorNotice } from './editor';

export function VerdictBadge({ result }: { result: SessionResult | null }) {
  if (!result)
    return (
      <Badge variant="outline" className="verdict">
        Not run
      </Badge>
    );
  if (result.state === 'failed')
    return (
      <Badge className="verdict danger">
        <CircleAlert />
        Run failed
      </Badge>
    );
  switch (result.analysis.verdict) {
    case 'confirmed_violation':
      return (
        <Badge className="verdict danger">
          <CircleAlert />
          Canary exposed
        </Badge>
      );
    case 'no_violation_observed':
      return (
        <Badge className="verdict success">
          <Check />
          No exposure observed
        </Badge>
      );
    default:
      return (
        <Badge className="verdict warning">
          <Clock3 />
          Inconclusive
        </Badge>
      );
  }
}

export function EmptyResponse({
  running = false,
  title = 'Ready when you are',
  description = 'Send an input to inspect the agent response, session events, and evidence.',
}: {
  running?: boolean;
  title?: string;
  description?: string;
}) {
  return (
    <div className="empty-response" aria-live="polite">
      <div className="empty-icon">
        {running ? <LoaderCircle className="animate-spin" /> : <ScanLine />}
      </div>
      <h3>{running ? 'Waiting for target…' : title}</h3>
      <p>
        {running
          ? 'The response and analysis will appear when the run completes.'
          : description}
      </p>
    </div>
  );
}

export function SessionResponse({
  result,
  running = false,
  error = null,
  stale = false,
  splitTranscript = false,
}: {
  result: SessionResult | null;
  running?: boolean;
  error?: string | null;
  stale?: boolean;
  splitTranscript?: boolean;
}) {
  const ready = !running && !error && result !== null;
  const rawResult = result ? resultForDisplay(result) : null;
  const observation = result ? observationFromResult(result) : null;
  const responseViews = observation
    ? ['transcript', 'observations', 'events', 'analysis', 'raw']
    : ['transcript', 'events', 'analysis', 'raw'];
  return (
    <section
      className="work-pane"
      aria-label="Captured response"
      aria-busy={running}
    >
      <div className="pane-heading">
        <div className="pane-title">
          <ArrowDownLeft />
          <h2>Response</h2>
          {result?.metadata?.target && (
            <span
              className={`target-environment ${result.metadata.target.environment}`}
            >
              {result.metadata.target.name}
            </span>
          )}
          {result?.metadata?.response_mapper?.status === 'completed' && (
            <span className="pane-label">LLM normalized</span>
          )}
          {result?.metadata?.response_mapper?.status === 'failed' && (
            <span className="pane-label">Mapper fallback</span>
          )}
        </div>
        <div className="pane-actions">
          {running ? (
            <Badge className="verdict">Running</Badge>
          ) : error ? (
            <Badge className="verdict danger">Request failed</Badge>
          ) : (
            <VerdictBadge result={result} />
          )}
          <CopyButton
            key={result?.run_id ?? 'empty'}
            text={ready ? result.response_text : ''}
          />
        </div>
      </div>
      {ready && stale && (
        <div className="stale-notice">
          Request edited. Showing the last submitted version.
        </div>
      )}
      <Tabs defaultValue="transcript" className="response-tabs">
        <TabsList aria-label="Response views">
          <TabsTrigger value="transcript">Messages</TabsTrigger>
          {observation && (
            <TabsTrigger value="observations">Observations</TabsTrigger>
          )}
          <TabsTrigger value="events">
            Events{ready ? ` (${result.events.length})` : ''}
          </TabsTrigger>
          <TabsTrigger value="analysis">Analysis</TabsTrigger>
          <TabsTrigger value="raw">Raw</TabsTrigger>
        </TabsList>
        {responseViews.map((view) => (
          <TabsContent key={view} value={view} className="response-body">
            {running ? (
              <EmptyResponse running />
            ) : error ? (
              <ErrorNotice message={error} />
            ) : !result ? (
              <EmptyResponse />
            ) : view === 'transcript' ? (
              <Transcript result={result} split={splitTranscript} />
            ) : view === 'observations' && observation ? (
              <Observations observation={observation} />
            ) : view === 'events' ? (
              <EventTable result={result} />
            ) : view === 'analysis' ? (
              <Analysis result={result} />
            ) : (
              <pre className="raw-response">
                {JSON.stringify(rawResult, null, 2)}
              </pre>
            )}
          </TabsContent>
        ))}
      </Tabs>
      <div className="pane-footer">
        <span>
          {running
            ? 'Waiting for completion'
            : error
              ? 'Request unsuccessful'
              : result
                ? `${result.duration_ms} ms · ${result.events.length} events`
                : 'No response captured'}
        </span>
        <span>
          {ready
            ? `${result.response_text.length} characters`
            : 'Simulator / text response'}
        </span>
      </div>
    </section>
  );
}

interface CapturedObservation {
  kind: string;
  phase: string;
  source: string;
  text: string;
  metadata: Record<string, unknown>;
  screenshot_url?: string;
}

interface ObservationPair {
  before?: CapturedObservation | null;
  after?: CapturedObservation | null;
}

function observationFromResult(result: SessionResult): ObservationPair | null {
  const value = result.metadata?.exchange?.response_metadata?.observation;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as ObservationPair;
}

function Observations({ observation }: { observation: ObservationPair }) {
  return (
    <div className="observation-grid">
      {(['before', 'after'] as const).map((phase) => {
        const captured = observation[phase];
        if (!captured) return null;
        const screenshot = captured.screenshot_url
          ? resolveArtifactUrl(captured.screenshot_url)
          : null;
        return (
          <section className="observation-card" key={phase}>
            <div className="transcript-label">
              <ScanLine /> {phase.toUpperCase()}
              <span className="label-meta">{captured.kind} observer</span>
            </div>
            {screenshot && (
              <Image
                src={screenshot}
                alt={`${phase} stimulus observation`}
                width={720}
                height={450}
                unoptimized
              />
            )}
            <pre>{captured.text}</pre>
            <small>{captured.source}</small>
          </section>
        );
      })}
    </div>
  );
}

function resultForDisplay(result: SessionResult): SessionResult {
  const audio =
    result.metadata?.exchange?.response_metadata?.response_audio_data_url;
  if (typeof audio !== 'string') return result;
  return {
    ...result,
    metadata: {
      ...result.metadata,
      exchange: {
        ...result.metadata?.exchange,
        response_metadata: {
          ...result.metadata?.exchange?.response_metadata,
          response_audio_data_url: '<audio omitted; playable in Messages>',
        },
      },
    },
  };
}

function Transcript({
  result,
  split,
}: {
  result: SessionResult;
  split: boolean;
}) {
  const responseMetadata = result.metadata?.exchange?.response_metadata;
  const audioValue = responseMetadata?.response_audio_url;
  const legacyAudioValue = responseMetadata?.response_audio_data_url;
  const responseAudio =
    typeof audioValue === 'string'
      ? resolveArtifactUrl(audioValue)
      : typeof legacyAudioValue === 'string'
        ? legacyAudioValue
        : null;
  const parts = result.canary
    ? result.response_text.split(result.canary)
    : [result.response_text];
  return (
    <div className={'transcript' + (split ? ' is-split' : '')}>
      <div className="transcript-message request-message">
        <div className="transcript-label">
          <ArrowUpRight /> REQUEST{' '}
          <span className="label-meta">rendered agent input</span>
        </div>
        <pre>{result.script}</pre>
      </div>
      <div className="transcript-message response-message">
        <div className="transcript-label">
          <MessageSquare /> RESPONSE{' '}
          <span className="label-meta">captured response</span>
        </div>
        <pre className="agent-response">
          {parts.map((part, index) => (
            <span key={index}>
              {index > 0 && (
                <mark className="canary-highlight">{result.canary}</mark>
              )}
              {part}
            </span>
          ))}
        </pre>
        {responseAudio && (
          <div className="voice-response-player">
            <span>Captured spoken response</span>
            <audio controls preload="metadata" src={responseAudio}>
              <track
                kind="captions"
                srcLang="en"
                label="Captured transcript"
                src={`data:text/vtt;charset=utf-8,${encodeURIComponent(
                  `WEBVTT\n\n00:00.000 --> 23:59:59.000\n${result.response_text.replaceAll('\n', ' ')}`,
                )}`}
                default
              />
              Audio playback is not supported by this browser.
            </audio>
          </div>
        )}
      </div>
    </div>
  );
}

function EventTable({ result }: { result: SessionResult }) {
  return (
    <div className="table-scroll">
      <table className="data-table events-table">
        <caption className="sr-only">Ordered session events</caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Source</th>
            <th scope="col">Event</th>
          </tr>
        </thead>
        <tbody>
          {result.events.map((event) => (
            <tr key={event.sequence}>
              <td>{event.elapsed_ms} ms</td>
              <td>{event.source}</td>
              <td>
                <details>
                  <summary aria-label={`Inspect ${event.event_type}`}>
                    {event.event_type}
                  </summary>
                  <pre className="raw-response">
                    {JSON.stringify(event.data, null, 2)}
                  </pre>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Analysis({ result }: { result: SessionResult }) {
  const review = result.analysis.llm_review;
  const actions = result.metadata?.exchange?.actions ?? [];
  return (
    <div>
      <section className="analysis-block">
        <h3>Deterministic evidence</h3>
        <div className="mb-3">
          <VerdictBadge result={result} />
        </div>
        <ul>
          {result.analysis.evidence.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>
      {result.metadata?.target && (
        <section className="analysis-block">
          <h3>Observed target actions</h3>
          {actions.length ? (
            <ul>
              {actions.map((action, index) => (
                <li key={`${action.name}-${index}`}>
                  <code>{action.name}</code> {JSON.stringify(action.arguments)}
                </li>
              ))}
            </ul>
          ) : (
            <p>No structured target actions were extracted.</p>
          )}
        </section>
      )}
      <section className="analysis-block">
        <h3>
          LLM review <span className="pane-label">Secondary</span>
        </h3>
        <p>
          {review?.summary ??
            review?.error ??
            'No LLM review is configured for this workspace.'}
        </p>
        {review?.model && <p className="mt-2">Model: {review.model}</p>}
      </section>
      <section className="analysis-block">
        <h3>
          <FileText size={12} className="mr-1 inline" /> Interpretation
        </h3>
        <p>
          Results describe this target run. No observed canary exposure does not
          establish that an agent is secure.
        </p>
      </section>
    </div>
  );
}
