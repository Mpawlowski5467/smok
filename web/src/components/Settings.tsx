import { useState } from 'react';
import { Plus, Trash2, KeyRound, Cpu, Plug, Shield } from 'lucide-react';
import { Button } from './ui/button';
import { Dialog } from './ui/dialog';
import { api, type Data } from '@/lib/api';
export function Settings({
  settings,
  onClose,
  onSaved,
  onError,
}: {
  settings: Data;
  onClose: () => void;
  onSaved: (s: Data) => void;
  onError: (s: string) => void;
}) {
  const [tab, setTab] = useState('Models'),
    [models, setModels] = useState<Data[]>(settings.models),
    [def, setDef] = useState(settings.default_model),
    [keys, setKeys] = useState<Data>({}),
    [servers, setServers] = useState<Data[]>(
      Object.entries(settings.mcp_servers).map(([name, value]) => ({ name, ...(value as Data) })),
    ),
    [mode, setMode] = useState(settings.permissions),
    [rules, setRules] = useState<Data[]>(settings.allow_rules),
    [sandbox, setSandbox] = useState(settings.sandbox),
    [saving, setSaving] = useState(false),
    [issue, setIssue] = useState('');
  const changeModel = (i: number, k: string, v: any) => {
    if (k === 'name' && def === models[i].name) setDef(v);
    setModels((ms) => ms.map((m, j) => (i === j ? { ...m, [k]: v } : m)));
  };
  const changeServer = (i: number, k: string, v: any) =>
    setServers((ms) => ms.map((m, j) => (i === j ? { ...m, [k]: v } : m)));
  const save = async () => {
    setSaving(true);
    try {
      const profiles: Data = {};
      for (const m of models) {
        const { name, model, ...fields } = m;
        if (!name?.includes('/')) throw Error('Use provider/model for each model profile.');
        profiles[name] = fields;
      }
      const mcp_servers: Data = {};
      for (const s of servers) {
        const { name, ...config } = s;
        if (!name || mcp_servers[name]) throw Error('MCP server names must be unique.');
        mcp_servers[name] = config;
      }
      const result = await api('/settings', 'PUT', {
        revision: settings.revision,
        profiles,
        default_model: def,
        secrets: Object.fromEntries(Object.entries(keys).filter(([, v]) => v !== '')),
        mcp_servers,
        permissions: mode,
        allow_rules: rules,
        sandbox,
      });
      onSaved(result);
      onClose();
    } catch (e) {
      setIssue(String(e));
      onError(String(e));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={onClose}
      title="Workspace settings"
      description="Configure this workspace. Keys stay on this computer."
      wide
    >
      <div className="settings-tabs">
        {[
          [Cpu, 'Models'],
          [KeyRound, 'API keys'],
          [Plug, 'MCP servers'],
          [Shield, 'Permissions'],
        ].map(([Icon, label]: any) => (
          <Button
            key={label}
            variant={tab === label ? 'outline' : 'ghost'}
            onClick={() => setTab(label)}
          >
            <Icon size={15} />
            {label}
          </Button>
        ))}
      </div>
      <div className="settings-body">
        {issue && (
          <p role="alert" className="text-danger">
            {issue}
          </p>
        )}
        {tab === 'Models' && (
          <>
            <p className="muted">
              Use a provider/model selector. Enable vision only if your endpoint supports image
              input. Prices are your estimates per million tokens.
            </p>
            {models.map((m, i) => (
              <section className="form-card" key={i}>
                <div className="row-between">
                  <strong>Model {i + 1}</strong>
                  <label className="check">
                    <input
                      type="radio"
                      name="default-model"
                      checked={def === m.name}
                      onChange={() => setDef(m.name)}
                    />
                    Default
                  </label>
                </div>
                <div className="form-grid">
                  <label>
                    Model selector
                    <input
                      aria-label={`Model selector ${i + 1}`}
                      value={m.name}
                      onChange={(e) => changeModel(i, 'name', e.target.value)}
                      placeholder="ollama/your-model"
                    />
                  </label>
                  <label>
                    Endpoint
                    <input
                      value={m.base_url || ''}
                      onChange={(e) => changeModel(i, 'base_url', e.target.value)}
                      placeholder="http://127.0.0.1:11434/v1"
                    />
                  </label>
                  <label>
                    Context limit
                    <input
                      type="number"
                      min="1024"
                      value={m.context_window || 32768}
                      onChange={(e) => changeModel(i, 'context_window', +e.target.value)}
                    />
                  </label>
                  <label>
                    Output limit
                    <input
                      type="number"
                      min="1"
                      value={m.max_output_tokens || 4096}
                      onChange={(e) => changeModel(i, 'max_output_tokens', +e.target.value)}
                    />
                  </label>
                  <label>
                    Reasoning effort
                    <select
                      aria-label="Reasoning effort"
                      value={m.reasoning_effort ?? ''}
                      disabled={m.adapter === 'anthropic'}
                      onChange={(e) => changeModel(i, 'reasoning_effort', e.target.value || null)}
                    >
                      <option value="">Provider default</option>
                      {['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'].map(
                        (effort) => (
                          <option key={effort} value={effort}>
                            {effort}
                          </option>
                        ),
                      )}
                    </select>
                  </label>
                  <label>
                    Prompt style
                    <select
                      aria-label="Prompt style"
                      value={m.prompt_style || 'full'}
                      onChange={(e) => changeModel(i, 'prompt_style', e.target.value)}
                    >
                      <option value="full">Full guidance</option>
                      <option value="lean">Lean guidance</option>
                    </select>
                  </label>
                  {(['temperature', 'top_p'] as const).map((field) => (
                    <label key={field}>
                      {field === 'temperature' ? 'Temperature' : 'Top-p'}
                      <input
                        type="number"
                        min="0"
                        max={field === 'temperature' ? 2 : 1}
                        step="0.05"
                        placeholder="Endpoint default"
                        value={m[field] ?? ''}
                        disabled={m.adapter === 'anthropic'}
                        onChange={(e) =>
                          changeModel(i, field, e.target.value === '' ? null : +e.target.value)
                        }
                      />
                    </label>
                  ))}
                  <label>
                    Tool set
                    <select
                      aria-label="Tool set"
                      value={m.tool_set || 'full'}
                      onChange={(e) => changeModel(i, 'tool_set', e.target.value)}
                    >
                      <option value="full">All available tools</option>
                      <option value="coding">Coding tools</option>
                      <option value="minimal">Basic file and shell tools</option>
                    </select>
                  </label>
                  <label>
                    Edit format
                    <select
                      aria-label="Edit format"
                      value={m.edit_format || 'both'}
                      onChange={(e) => changeModel(i, 'edit_format', e.target.value)}
                    >
                      <option value="both">Exact edits and full files</option>
                      <option value="exact">Exact edits for existing files</option>
                      <option value="whole_file">Full file replacement</option>
                    </select>
                  </label>
                  <label>
                    Input $ / million
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={m.prices?.input ?? ''}
                      onChange={(e) =>
                        changeModel(i, 'prices', { ...m.prices, input: +e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Output $ / million
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={m.prices?.output ?? ''}
                      onChange={(e) =>
                        changeModel(i, 'prices', { ...m.prices, output: +e.target.value })
                      }
                    />
                  </label>
                </div>
                <p className="muted">
                  Smaller tool sets reduce context. Approval rules and Plan mode still apply.
                  Reasoning support varies by model. Provider default leaves its setting unchanged;
                  none requests no thinking when supported. Lower effort can change answer quality.
                </p>
                <div className="button-row">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={!!m.vision}
                      onChange={(e) => changeModel(i, 'vision', e.target.checked)}
                    />
                    Vision input
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={!!m.local}
                      onChange={(e) => changeModel(i, 'local', e.target.checked)}
                    />
                    Local inference ($0 API cost)
                  </label>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Remove model"
                    disabled={models.length === 1 || def === m.name}
                    onClick={() => setModels(models.filter((_, j) => i !== j))}
                  >
                    <Trash2 size={15} />
                  </Button>
                </div>
              </section>
            ))}
            <Button
              variant="outline"
              onClick={() =>
                setModels([
                  ...models,
                  { name: '', context_window: 32768, max_output_tokens: 4096, vision: false },
                ])
              }
            >
              <Plus size={15} />
              Add model
            </Button>
          </>
        )}
        {tab === 'API keys' && (
          <>
            <p className="muted">
              Saved keys are stored in a private file inside this workspace’s .smok folder (owner
              access only). They are never returned by the API. Environment keys can also be used.
            </p>
            {settings.secrets.map((s: Data) => (
              <div className="key-row" key={s.name}>
                <label>
                  {s.name}
                  <input
                    type="password"
                    autoComplete="new-password"
                    aria-label={s.name}
                    value={keys[s.name] || ''}
                    onChange={(e) => setKeys({ ...keys, [s.name]: e.target.value })}
                    placeholder={
                      keys[s.name] === null
                        ? 'Saved key will be removed'
                        : s.configured
                          ? 'Configured · enter to replace'
                          : 'Paste key'
                    }
                  />
                </label>
                {s.saved && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={'Remove ' + s.name}
                    onClick={() => setKeys({ ...keys, [s.name]: null })}
                  >
                    <Trash2 size={16} />
                  </Button>
                )}
              </div>
            ))}
            <p className="small muted">
              After saving a new provider model, its key field appears here. Empty fields leave
              existing keys unchanged.
            </p>
          </>
        )}
        {tab === 'MCP servers' && (
          <>
            <p className="muted">
              Saving a server does not start it. Connect through the Tools menu; executable actions
              still follow your permission policy.
            </p>
            {servers.map((s, i) => (
              <section className="form-card" key={i}>
                <div className="form-grid">
                  <label>
                    Name
                    <input
                      value={s.name}
                      onChange={(e) => changeServer(i, 'name', e.target.value)}
                    />
                  </label>
                  <label>
                    Transport
                    <select
                      value={s.url !== undefined ? 'http' : 'stdio'}
                      onChange={(e) =>
                        setServers(
                          servers.map((a, j) =>
                            j === i
                              ? {
                                  name: s.name,
                                  ...(e.target.value === 'http'
                                    ? { url: 'https://' }
                                    : { command: '', args: [] }),
                                }
                              : a,
                          ),
                        )
                      }
                    >
                      <option value="stdio">Local command (stdio)</option>
                      <option value="http">Streamable HTTP</option>
                    </select>
                  </label>
                </div>
                {s.url !== undefined ? (
                  <label>
                    Server URL
                    <input value={s.url} onChange={(e) => changeServer(i, 'url', e.target.value)} />
                  </label>
                ) : (
                  <>
                    <label>
                      Executable
                      <input
                        value={s.command || ''}
                        onChange={(e) => changeServer(i, 'command', e.target.value)}
                        placeholder="npx"
                      />
                    </label>
                    <label>
                      Arguments (one per line)
                      <textarea
                        value={(s.args || []).join('\n')}
                        onChange={(e) => changeServer(i, 'args', e.target.value.split('\n'))}
                        placeholder={'-y\n@playwright/mcp@latest'}
                      />
                    </label>
                  </>
                )}
                <div className="form-grid">
                  <label>
                    Environment names (one per line)
                    <textarea
                      value={(s.env_vars || []).join('\n')}
                      onChange={(e) =>
                        changeServer(i, 'env_vars', e.target.value.split('\n').filter(Boolean))
                      }
                    />
                  </label>
                  <label>
                    Read-only tools in plan mode
                    <textarea
                      value={(s.read_only || []).join('\n')}
                      onChange={(e) =>
                        changeServer(i, 'read_only', e.target.value.split('\n').filter(Boolean))
                      }
                    />
                  </label>
                </div>
                {s.url !== undefined && (
                  <label>
                    Headers from environment (Header=ENV_NAME, one per line)
                    <textarea
                      value={Object.entries(s.headers_env || {})
                        .map(([k, v]) => `${k}=${v}`)
                        .join('\n')}
                      onChange={(e) =>
                        changeServer(
                          i,
                          'headers_env',
                          Object.fromEntries(
                            e.target.value
                              .split('\n')
                              .filter(Boolean)
                              .map((line) => {
                                const [k, ...v] = line.split('=');
                                return [k, v.join('=')];
                              }),
                          ),
                        )
                      }
                    />
                  </label>
                )}
                <Button
                  variant="ghost"
                  onClick={() => setServers(servers.filter((_, j) => i !== j))}
                >
                  <Trash2 size={14} />
                  Remove server
                </Button>
              </section>
            ))}
            <Button
              variant="outline"
              onClick={() => setServers([...servers, { name: '', command: '', args: [] }])}
            >
              <Plus size={15} />
              Add server
            </Button>
          </>
        )}
        {tab === 'Permissions' && (
          <>
            <label>
              Default permission mode
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="ask">Ask before writes and commands</option>
                <option value="auto-edit">Allow file edits; ask before commands</option>
                <option value="full-auto">Allow all available actions</option>
              </select>
            </label>
            <div className="form-grid">
              <label>
                Shell backend
                <select
                  value={sandbox.backend}
                  onChange={(e) => setSandbox({ ...sandbox, backend: e.target.value })}
                >
                  <option value="host">Host computer</option>
                  <option value="docker">Docker container</option>
                </select>
              </label>
              <label>
                Docker image
                <input
                  value={sandbox.image}
                  onChange={(e) => setSandbox({ ...sandbox, image: e.target.value })}
                />
              </label>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={sandbox.network}
                onChange={(e) => setSandbox({ ...sandbox, network: e.target.checked })}
              />
              Allow Docker network access
            </label>
            <h3>Saved allow rules</h3>
            <p className="small muted">
              Rules are scoped to this workspace. Plan mode continues to block mutations.
            </p>
            {rules.map((r, i) => (
              <div className="rule-row" key={i}>
                <div>
                  <strong>{r.tool}</strong>
                  <code>{r.path || r.command || r.name || r.key}</code>
                  <span className="muted small">{r.match || 'Exact approval fingerprint'}</span>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Remove rule"
                  onClick={() => setRules(rules.filter((_, j) => i !== j))}
                >
                  <Trash2 size={15} />
                </Button>
              </div>
            ))}
            <RuleForm add={(r) => setRules([...rules, r])} />
          </>
        )}
      </div>
      <div className="dialog-footer">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button disabled={saving} onClick={save}>
          {saving ? 'Saving…' : 'Save settings'}
        </Button>
      </div>
    </Dialog>
  );
}
function RuleForm({ add }: { add: (r: Data) => void }) {
  const [type, setType] = useState('file_edit'),
    [value, setValue] = useState(''),
    [pattern, setPattern] = useState(false);
  return (
    <div className="form-card">
      <div className="form-grid">
        <label>
          Rule type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="file_edit">File edit</option>
            <option value="run_shell">Shell command</option>
          </select>
        </label>
        <label>
          {type === 'file_edit' ? 'Relative path' : 'Complete command'}
          <input value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
      </div>
      <label className="check">
        <input type="checkbox" checked={pattern} onChange={(e) => setPattern(e.target.checked)} />
        Use a pattern (otherwise exact)
      </label>
      <Button
        variant="outline"
        disabled={!value}
        onClick={() => {
          add({
            tool: type,
            [type === 'file_edit' ? 'path' : 'command']: value,
            match: pattern ? (type === 'file_edit' ? 'glob' : 'argv') : 'exact',
          });
          setValue('');
        }}
      >
        Add allow rule
      </Button>
    </div>
  );
}
