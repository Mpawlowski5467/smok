import { useState } from 'react';
import { Dialog } from './ui/dialog';
import { Button } from './ui/button';
import type { Data } from '@/lib/api';
export function Workflows({
  view,
  models,
  onClose,
  run,
}: {
  view: Data;
  models: Data[];
  onClose: () => void;
  run: (a: string, d: Data) => void;
}) {
  const [action, setAction] = useState('review'),
    [text, setText] = useState(''),
    [role, setRole] = useState('explore'),
    [selected, setSelected] = useState<string[]>([]),
    [check, setCheck] = useState(''),
    [name, setName] = useState(''),
    [base, setBase] = useState(''),
    [candidate, setCandidate] = useState(1),
    [values, setValues] = useState<Data>({});
  const submit = () => {
    let data: Data = {};
    if (action === 'review') data = { base };
    if (action === 'oracle') data = { question: text };
    if (action === 'delegate') data = { tasks: [{ role, task: text }] };
    if (action === 'council') data = { task: text, models: selected, check };
    if (action === 'start_process') data = { command: text };
    if (action === 'mcp') data = { name };
    if (['skill', 'recipe', 'command'].includes(action)) data = { name, arguments: text, values };
    if (action === 'replay') data = { session: name, base, check };
    if (action === 'accept') data = { run: name, candidate };
    run(action, data);
    onClose();
  };
  const options = [
    ['review', 'Review changes'],
    ['reload', 'Reload extensions'],
    ['compact', 'Compact context'],
    ['handoff', 'Export handoff'],
    ['oracle', 'Ask an oracle'],
    ['delegate', 'Delegate a task'],
    ['council', 'Model council'],
    ['accept', 'Accept council candidate'],
    ['replay', 'Replay a session'],
    ['start_process', 'Start background command'],
    ['mcp', 'Connect MCP server'],
    ['skill', 'Run skill'],
    ['recipe', 'Run recipe'],
    ['command', 'Run custom command'],
  ];
  return (
    <Dialog
      open
      onOpenChange={onClose}
      title="Workspace tools"
      description="Run the same workflows available in the CLI."
    >
      <div className="settings-body">
        <label>
          Workflow
          <select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setName('');
              setValues({});
            }}
          >
            {options.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        {['oracle', 'delegate', 'council', 'start_process', 'skill', 'recipe', 'command'].includes(
          action,
        ) && (
          <label>
            {action === 'start_process'
              ? 'Command'
              : action === 'skill' || action === 'recipe' || action === 'command'
                ? 'Arguments'
                : 'Task'}
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} />
          </label>
        )}
        {action === 'delegate' && (
          <label>
            Role
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {['explore', 'plan', 'edit', 'review'].map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </label>
        )}
        {['review', 'replay'].includes(action) && (
          <label>
            Base Git revision (optional)
            <input value={base} onChange={(e) => setBase(e.target.value)} />
          </label>
        )}
        {['replay', 'accept'].includes(action) && (
          <label>
            {action === 'replay' ? 'Session ID' : 'Council run ID'}
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
        )}
        {action === 'accept' && (
          <label>
            Candidate (1–3)
            <input
              type="number"
              min="1"
              max="3"
              value={candidate}
              onChange={(e) => setCandidate(+e.target.value)}
            />
          </label>
        )}
        {action === 'council' && (
          <fieldset>
            <legend>Select 2–3 model profiles</legend>
            {models.map((m) => (
              <label key={m.name} className="check">
                <input
                  type="checkbox"
                  checked={selected.includes(m.name)}
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? [...selected, m.name]
                        : selected.filter((v) => v !== m.name),
                    )
                  }
                />
                {m.name}
              </label>
            ))}
          </fieldset>
        )}
        {['replay', 'council'].includes(action) && (
          <label>
            Check command {action === 'council' ? '(required)' : '(optional)'}
            <input
              value={check}
              onChange={(e) => setCheck(e.target.value)}
              placeholder="python -m pytest"
            />
          </label>
        )}
        {action === 'mcp' && (
          <label>
            Server
            <select value={name} onChange={(e) => setName(e.target.value)}>
              <option value="">Choose a server</option>
              {(view.extensions?.mcp_servers || []).map((s: Data) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {['skill', 'recipe', 'command'].includes(action) && (
          <>
            <label>
              Extension
              <select
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setValues({});
                }}
              >
                <option value="">Choose an extension</option>
                {(
                  view.extensions?.[
                    action === 'skill' ? 'skills' : action === 'recipe' ? 'recipes' : 'commands'
                  ] || []
                ).map((d: Data) => (
                  <option key={d.name} value={d.name}>
                    {d.name} · {d.description}
                  </option>
                ))}
              </select>
            </label>
            {Object.entries(
              (
                view.extensions?.[
                  action === 'skill' ? 'skills' : action === 'recipe' ? 'recipes' : 'commands'
                ] || []
              ).find((d: Data) => d.name === name)?.parameters || {},
            ).map(([key, value]) => (
              <label key={key}>
                {key}
                {value === null ? ' (required)' : ''}
                <input
                  value={values[key] ?? value ?? ''}
                  onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                />
              </label>
            ))}
          </>
        )}
        {action === 'compact' && (
          <p className="muted">
            Summarizes older complete exchanges, keeping recent messages and your pins. Uses one
            model request.
          </p>
        )}
        {action === 'handoff' && (
          <p className="muted">
            Creates an editable session summary in the workspace metadata folder.
          </p>
        )}
        {action === 'accept' && (
          <p className="muted">
            Applies the selected candidate only if the source workspace still matches the council
            baseline.
          </p>
        )}
      </div>
      <div className="dialog-footer">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={submit}>Run workflow</Button>
      </div>
    </Dialog>
  );
}
