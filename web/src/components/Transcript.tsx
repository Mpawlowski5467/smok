import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Check, ChevronRight, CircleAlert, GitBranch, Terminal, User, X, Zap } from 'lucide-react';
import { Button } from './ui/button';
import type { Data, SmokEvent } from '@/lib/api';
export function Prose({ text }: { text: string }) {
  return (
    <div className="prose">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
          img: ({ alt, src }) => <span className="muted">[Image: {alt || src}]</span>,
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
export function Diff({ diff }: { diff: string }) {
  return (
    <pre className="diff" aria-label="Proposed changes">
      {diff.split('\n').map((line, i) => (
        <span
          key={i}
          className={
            line.startsWith('+') && !line.startsWith('+++')
              ? 'added'
              : line.startsWith('-') && !line.startsWith('---')
                ? 'removed'
                : line.startsWith('@@')
                  ? 'hunk'
                  : ''
          }
        >
          {line || ' '}
        </span>
      ))}
    </pre>
  );
}
export function Approval({
  item,
  decide,
  disabled,
}: {
  item: Data;
  decide: (id: string, decision: string) => void;
  disabled: boolean;
}) {
  return (
    <section className="approval" aria-label="Permission requested">
      <div className="approval-title">
        <CircleAlert size={17} />
        <strong>{item.diff ? 'Review this change' : 'Smok needs your permission'}</strong>
      </div>
      <code>{item.name || item.tool || 'Action'}</code>
      {item.path && <div className="file-path">{item.path}</div>}
      {item.workspace && <div className="muted small">Workspace: {item.workspace}</div>}
      {item.diff ? (
        <Diff diff={item.diff} />
      ) : (
        <pre className="arguments">{JSON.stringify(item.arguments || item, null, 2)}</pre>
      )}
      <details className="approval-details">
        <summary>Permission scope and execution details</summary>
        <pre>{JSON.stringify(item, null, 2)}</pre>
      </details>
      <div className="muted small">
        {item.backend === 'docker' ? 'Docker shell · ' + item.image : 'Shell backend: host'} ·
        Always allow saves this exact action or file scope.
      </div>
      <div className="button-row">
        <Button disabled={disabled} onClick={() => decide(item.request_id, 'allow')}>
          <Check size={15} />
          {item.diff ? 'Accept change' : 'Allow once'}
        </Button>
        <Button
          variant="outline"
          disabled={disabled}
          onClick={() => decide(item.request_id, 'always')}
        >
          Always allow
        </Button>
        <Button variant="ghost" disabled={disabled} onClick={() => decide(item.request_id, 'deny')}>
          <X size={15} />
          {item.diff ? 'Reject change' : 'Deny'}
        </Button>
      </div>
    </section>
  );
}
export function Transcript({
  events,
  pending,
  decide,
  disabled = false,
}: {
  events: SmokEvent[];
  pending: Data[];
  decide: (id: string, d: string) => void;
  disabled?: boolean;
}) {
  const visible = events.filter((e) => !e.data.worker);
  const results = new Map(
    visible.filter((e) => e.type === 'tool_result').map((e) => [e.data.id, e.data]),
  );
  const diffs = new Map(visible.filter((e) => e.type === 'diff').map((e) => [e.data.id, e.data]));
  const perms = new Map(
    visible.filter((e) => e.type === 'permission_resolved').map((e) => [e.data.id, e.data]),
  );
  return (
    <>
      {visible.map((e, i) => {
        if (e.type === 'history_restored')
          return (
            <Transcript
              key={i}
              events={e.data.messages.flatMap((m: Data) =>
                m.content.map((b: Data) =>
                  b.type === 'text'
                    ? {
                        type: m.role === 'user' ? 'turn_started' : 'text_delta',
                        data: m.role === 'user' ? { prompt: b.text } : { text: b.text },
                      }
                    : b.type === 'tool_call'
                      ? { type: 'tool_call', data: b }
                      : b.type === 'tool_result'
                        ? { type: 'tool_result', data: { ...b, id: b.tool_call_id } }
                        : { type: 'omitted', data: {} },
                ),
              )}
              pending={[]}
              decide={decide}
            />
          );
        if (e.type === 'turn_started' && !e.data.internal)
          return (
            <article key={i} className="message user-message">
              <div className="avatar user-avatar">
                <User size={16} />
              </div>
              <div className="message-body">
                <div className="message-label">You</div>
                <div className="user-text">{e.data.prompt}</div>
                {e.data.images?.length > 0 && (
                  <div className="sent-images">
                    {e.data.images.map((image: Data, j: number) => (
                      <img
                        key={j}
                        src={`data:${image.media_type};base64,${image.data}`}
                        alt={`Attached image ${j + 1}`}
                      />
                    ))}
                  </div>
                )}
              </div>
            </article>
          );
        if (e.type === 'text_delta')
          return (
            <article key={i} className="message assistant-message">
              <div className="avatar dragon-avatar">
                <img src="/brand/dragon_logo.png" alt="Smok" />
              </div>
              <div className="message-body">
                <div className="message-label">
                  Smok <span>CODING COMPANION</span>
                </div>
                <Prose text={e.data.text} />
              </div>
            </article>
          );
        if (e.type === 'tool_call') {
          const result = results.get(e.data.id),
            diff = diffs.get(e.data.id),
            permission = perms.get(e.data.id);
          return (
            <details key={i} className="tool-call">
              <summary>
                <ChevronRight size={14} />
                <Terminal size={14} />
                <span>{e.data.name}</span>
                <span className={'tool-status ' + (result?.is_error ? 'text-danger' : '')}>
                  {result ? (result.is_error ? 'Needs attention' : 'Done') : 'Working'}
                </span>
              </summary>
              <pre>{e.data.arguments}</pre>
              {diff && (
                <>
                  <div className="file-path">{diff.path}</div>
                  <Diff diff={diff.diff} />
                </>
              )}
              {permission && (
                <div className="small muted">
                  {permission.approved ? 'Approved' : 'Denied'} · {permission.source}
                </div>
              )}
              {result && (
                <pre className={result.is_error ? 'text-danger' : ''}>{result.content}</pre>
              )}
            </details>
          );
        }
        if (e.type === 'escalation')
          return (
            <div key={i} className="event-banner">
              <Zap size={16} />
              <div>
                Escalating to <strong>{e.data.to}</strong>
                <div className="small muted">
                  {e.data.reason?.replaceAll('_', ' ')} · Prior evidence carried forward
                </div>
              </div>
            </div>
          );
        if (e.type === 'model_retry')
          return (
            <div role="status" key={i} className="event-banner">
              <CircleAlert size={16} />
              {e.data.message}
            </div>
          );
        if (['error', 'budget_exhausted', 'turn_time_limit'].includes(e.type))
          return (
            <div role="alert" key={i} className="event-banner error-banner">
              <CircleAlert size={16} />
              {e.data.message}
            </div>
          );
        if (e.type === 'turn_finished' && e.data.reason !== 'complete')
          return (
            <div key={i} className="muted turn-end">
              Turn ended · {e.data.reason?.replaceAll('_', ' ')}
            </div>
          );
        if (e.type === 'checkpoint_restored')
          return (
            <div key={i} className="event-banner">
              <GitBranch size={16} />
              Restored files · Checkpoint {e.data.id}
            </div>
          );
        if (
          [
            'action_result',
            'council_finished',
            'shadow_finished',
            'replay_finished',
            'handoff_exported',
          ].includes(e.type)
        )
          return (
            <details key={i} className="tool-call">
              <summary>
                <ChevronRight size={14} />
                {e.type.replaceAll('_', ' ')}
              </summary>
              <pre>{e.data.content || JSON.stringify(e.data, null, 2)}</pre>
            </details>
          );
        return null;
      })}
      {pending.map((item) => (
        <Approval key={item.request_id} item={item} decide={decide} disabled={disabled} />
      ))}
    </>
  );
}
