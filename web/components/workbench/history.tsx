'use client';

import { useEffect, useState } from 'react';
import { History as HistoryIcon, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { listRuns, type SessionResult } from '@/lib/workbench-api';
import { ErrorNotice, errorMessage } from './editor';
import {
  EmptyResponse,
  SessionResponse,
  VerdictBadge,
} from './session-response';

export function History() {
  const [runs, setRuns] = useState<SessionResult[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listRuns()
      .then((response) => {
        if (active) {
          setRuns(response.runs);
          setLoading(false);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(errorMessage(caught));
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setRuns((await listRuns()).runs);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  const selectedRun =
    runs.find((run) => run.run_id === selected) ?? runs[0] ?? null;
  return (
    <div className="tool-view">
      <div className="action-toolbar">
        <div className="toolbar-heading">
          <h1>Run history</h1>
          <span>Latest 50 runs stored in this workspace</span>
        </div>
        <Button
          variant="outline"
          className="wb-button"
          onClick={refresh}
          disabled={loading}
        >
          <RefreshCw className={loading ? 'animate-spin' : ''} />
          Refresh
        </Button>
      </div>
      <div className="history-workspace">
        <section
          className="results-pane"
          aria-label="Saved runs"
          aria-busy={loading}
        >
          <div className="pane-heading">
            <div className="pane-title">
              <HistoryIcon />
              <h2>Saved runs</h2>
            </div>
            <span className="pane-label">{runs.length} runs</span>
          </div>
          {error ? (
            <ErrorNotice message={error} />
          ) : loading ? (
            <EmptyResponse
              title="Loading history…"
              description="Reading saved runs from your local workspace."
            />
          ) : runs.length === 0 ? (
            <EmptyResponse
              title="A clean slate"
              description="Completed Workbench and Campaign runs are saved here automatically."
            />
          ) : (
            <div className="table-scroll">
              <div
                className="result-grid history-result-grid"
                aria-label="Saved runs, newest first. Select a run to inspect it."
              >
                <div className="result-grid-head" aria-hidden="true">
                  <span>Run</span>
                  <span>Tool</span>
                  <span>Verdict</span>
                  <span>Time</span>
                </div>
                {runs.map((run) => {
                  const isSelected = selectedRun?.run_id === run.run_id;
                  return (
                    <button
                      key={run.run_id}
                      type="button"
                      className={
                        'result-grid-row' + (isSelected ? ' is-selected' : '')
                      }
                      onClick={() => setSelected(run.run_id)}
                      aria-label={`Inspect run ${run.run_id}`}
                      aria-pressed={isSelected}
                      data-testid="history-run-row"
                    >
                      <code className="result-grid-index">
                        {run.run_id.slice(0, 8)}
                      </code>
                      <span>
                        {run.mode === 'campaign' ? 'Campaign' : 'Workbench'}
                      </span>
                      <span>
                        <VerdictBadge result={run} />
                      </span>
                      <span>{run.duration_ms} ms</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </section>
        <SessionResponse
          key={selectedRun?.run_id ?? 'empty'}
          result={error || loading ? null : selectedRun}
        />
      </div>
    </div>
  );
}
