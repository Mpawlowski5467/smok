import { useEffect, useState } from 'react';
import { Copy, Link, Trash2 } from 'lucide-react';
import { Dialog } from './ui/dialog';
import { Button } from './ui/button';
import { Prose } from './Transcript';
import { api, type Data } from '@/lib/api';
export function SharedSession({ id }: { id: string }) {
  const [data, setData] = useState<Data>(),
    [error, setError] = useState('');
  useEffect(() => {
    api('/shares/' + id)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [id]);
  return (
    <div className="shared-page">
      <header>
        <img src="/brand/dragon_cli.png" alt="" />
        <strong>smok</strong>
        <span className="pill">READ ONLY</span>
      </header>
      {error ? (
        <div role="alert">{error}</div>
      ) : data ? (
        <>
          <h1>{data.title}</h1>
          <p className="muted">
            Frozen session snapshot · Images and workspace controls are omitted.
          </p>
          <ShareMessages messages={data.messages} />
        </>
      ) : (
        <p>Loading shared session…</p>
      )}
    </div>
  );
}
function ShareMessages({ messages }: { messages: Data[] }) {
  return (
    <>
      {messages.map((m, i) => (
        <article key={i} className="share-message">
          <div className="message-label">
            {m.role === 'assistant' ? 'Smok' : 'You / tool results'}
          </div>
          {m.content.map((b: Data, j: number) =>
            b.type === 'text' ? (
              <Prose key={j} text={b.text} />
            ) : (
              <details key={j}>
                <summary>{b.name || 'Tool result'}</summary>
                <pre>{b.content || b.arguments}</pre>
              </details>
            ),
          )}
        </article>
      ))}
    </>
  );
}
export function ShareDialog({
  id,
  onClose,
  onError,
}: {
  id: string;
  onClose: () => void;
  onError: (e: string) => void;
}) {
  const [tools, setTools] = useState(false),
    [preview, setPreview] = useState<Data>(),
    [shares, setShares] = useState<Data[]>([]),
    [busy, setBusy] = useState(false),
    [created, setCreated] = useState(''),
    [issue, setIssue] = useState('');
  const report = (error: string) => {
    setIssue(error);
    onError(error);
  };
  const refresh = () => api('/shares').then(setShares);
  useEffect(() => {
    refresh().catch((e) => report(String(e)));
  }, []);
  const inspect = async () => {
    setBusy(true);
    setIssue('');
    try {
      setPreview(await api(`/sessions/${id}/share-preview`, 'POST', { include_tools: tools }));
    } catch (e) {
      report(String(e));
    } finally {
      setBusy(false);
    }
  };
  const create = async () => {
    setBusy(true);
    setIssue('');
    try {
      const s = await api(`/sessions/${id}/shares`, 'POST', {
        include_tools: tools,
        digest: preview?.digest,
      });
      setCreated(s.url);
      setPreview(undefined);
      await refresh();
    } catch (e) {
      report(String(e));
    } finally {
      setBusy(false);
    }
  };
  const copy = async () => {
    setIssue('');
    try {
      await navigator.clipboard.writeText(created);
    } catch {
      report('Copy the displayed link manually.');
    }
  };
  return (
    <Dialog
      open
      onOpenChange={onClose}
      title="Share a session"
      description="Read-only links work on this computer while Smok is running, and expire after 7 days."
      wide
    >
      <div className="settings-body">
        {issue && <div role="alert">{issue}</div>}
        <p className="muted">
          Review the exact transcript before sharing. Messages can contain project details or
          secrets. Images, settings, and permission grants are omitted.
        </p>
        <label className="check">
          <input
            type="checkbox"
            checked={tools}
            onChange={(e) => {
              setTools(e.target.checked);
              setPreview(undefined);
            }}
          />
          Include tool calls and outputs
        </label>
        <Button variant="outline" onClick={inspect} disabled={busy}>
          Preview transcript
        </Button>
        {preview && (
          <>
            <div className="share-preview">
              <ShareMessages messages={preview.snapshot.messages} />
            </div>
            <Button disabled={busy} onClick={create}>
              <Link size={15} />
              Create link for this transcript
            </Button>
          </>
        )}
        {created && (
          <div className="created-link">
            <a href={created} target="_blank" rel="noreferrer">
              {created}
            </a>
            <Button aria-label="Copy share link" variant="ghost" size="icon" onClick={copy}>
              <Copy size={16} />
            </Button>
          </div>
        )}
        <h3>Existing links</h3>
        {shares.length === 0 && <p className="muted">No shared sessions yet.</p>}
        {shares.map((s) => (
          <div className="rule-row" key={s.id}>
            <a href={s.url} target="_blank" rel="noreferrer">
              {s.title}
            </a>
            <Button
              aria-label="Revoke share"
              variant="ghost"
              size="icon"
              onClick={() =>
                api('/shares/' + s.id, 'DELETE')
                  .then(refresh)
                  .catch((e) => report(String(e)))
              }
            >
              <Trash2 size={16} />
            </Button>
          </div>
        ))}
      </div>
    </Dialog>
  );
}
