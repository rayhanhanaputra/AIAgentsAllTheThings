'use client';

import { useState } from 'react';
import { Check, Copy, CircleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function CopyButton({
  text,
  label = 'Copy response',
}: {
  text: string;
  label?: string;
}) {
  const [feedback, setFeedback] = useState<'idle' | 'copied' | 'failed'>(
    'idle',
  );
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setFeedback('copied');
    } catch {
      setFeedback('failed');
    }
  }
  const title =
    feedback === 'copied'
      ? 'Copied to clipboard'
      : feedback === 'failed'
        ? 'Could not copy. Select and copy the text manually.'
        : label;
  return (
    <Button
      className="wb-button wb-icon"
      variant="ghost"
      onClick={copy}
      disabled={!text}
      aria-label={title}
      title={title}
    >
      {feedback === 'copied' ? (
        <Check />
      ) : feedback === 'failed' ? (
        <CircleAlert />
      ) : (
        <Copy />
      )}
    </Button>
  );
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="error-notice" role="alert">
      <strong>
        <CircleAlert size={14} /> Unable to complete the request
      </strong>
      <p>{message}</p>
      <p>
        Check the local API is running: <code>make workbench-api</code>
      </p>
    </div>
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof TypeError) return 'Could not reach the workbench API.';
  if (error instanceof Error && error.name === 'AbortError')
    return 'The request timed out. A run may still complete on the server; check History before retrying.';
  return error instanceof Error
    ? error.message
    : 'An unexpected error occurred.';
}
