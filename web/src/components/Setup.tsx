import { useEffect, useState } from 'react';
import { CheckCircle2, CircleAlert, CircleMinus, LoaderCircle } from 'lucide-react';
import { api, type Data } from '../lib/api';
import { Button } from './ui/button';
import { Dialog } from './ui/dialog';

export function SetupDialog({
  model,
  onClose,
  onSettings,
}: {
  model: string;
  onClose: () => void;
  onSettings: () => void;
}) {
  const [report, setReport] = useState<Data>(),
    [busy, setBusy] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    api('/diagnostics', 'POST', { model })
      .then((value) => {
        if (alive) setReport(value);
      })
      .catch((e) => {
        if (alive) setError(String(e).replace(/^Error: /, ''));
      })
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [model]);
  const check = async (probe: boolean) => {
    setBusy(true);
    setError('');
    try {
      setReport(await api('/diagnostics', 'POST', { model, probe }));
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={onClose}
      title="Check your setup"
      description="Check this workspace and selected model before your next task."
    >
      <div className="setup-content">
        <ol className="setup-steps">
          <li>Choose your installed or hosted model in Settings.</li>
          <li>Check the setup and model connection below.</li>
          <li>Start in Plan to explore, then use Build and review each proposed change.</li>
        </ol>
        <p className="setup-model">
          <strong>Selected model</strong>
          <code>{model}</code>
        </p>
        {error && (
          <p role="alert" className="setup-error">
            {error}
          </p>
        )}
        <p className="muted small">
          Connection checks request a model list using your configured credentials. Generation and
          tool support require a separate task.
        </p>
        <div className="setup-actions">
          <Button variant="outline" disabled={busy} onClick={() => check(false)}>
            Refresh local checks
          </Button>
          <Button disabled={busy} onClick={() => check(true)}>
            Check model connection
          </Button>
          <Button variant="ghost" onClick={onSettings}>
            Open model settings
          </Button>
        </div>
        <div aria-live="polite" aria-busy={busy}>
          {busy && (
            <p className="setup-progress">
              <LoaderCircle size={16} />
              Checking setup…
            </p>
          )}
          {report && (
            <ul className="setup-checks" aria-label="Setup results">
              {report.checks.map((c: Data) => {
                const Icon =
                  c.status === 'ok'
                    ? CheckCircle2
                    : c.status === 'skipped'
                      ? CircleMinus
                      : CircleAlert;
                return (
                  <li key={c.id} className={'setup-check setup-' + c.status}>
                    <Icon size={17} aria-hidden="true" />
                    <div>
                      <strong>{c.label}</strong>
                      <span className="setup-status">{c.status}</span>
                      <p>{c.detail}</p>
                      {c.remedy && <p className="setup-remedy">{c.remedy}</p>}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </Dialog>
  );
}
