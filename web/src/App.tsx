import { useCallback, useEffect, useRef, useState } from 'react';
import { version } from '../package.json';
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  CircleAlert,
  Coins,
  Folder,
  GitBranch,
  History,
  ImagePlus,
  Menu,
  Mic,
  PanelRightClose,
  PanelRightOpen,
  Pin,
  Plus,
  Search,
  Settings2,
  Share2,
  ShieldCheck,
  Sparkles,
  Square,
  Terminal,
  Unplug,
  Wrench,
  X,
  Zap,
} from 'lucide-react';
import { Button } from './components/ui/button';
import { Dialog } from './components/ui/dialog';
import { Settings } from './components/Settings';
import { SetupDialog } from './components/Setup';
import { ShareDialog, SharedSession } from './components/Share';
import { Workflows } from './components/Workflows';
import { Transcript } from './components/Transcript';
import { api, mergeEvent, money, number, type Data, type SmokEvent } from './lib/api';

type Attachment = { name: string; media_type: string; data: string };
export default function App() {
  const share = location.pathname.match(/^\/share\/([\w-]+)$/);
  return share ? <SharedSession id={share[1]} /> : <WorkspaceApp />;
}
function WorkspaceApp() {
  const [bootstrap, setBootstrap] = useState<Data>(),
    [view, setView] = useState<Data>(),
    [sessions, setSessions] = useState<Data[]>([]),
    [selected, setSelected] = useState(''),
    [events, setEvents] = useState<SmokEvent[]>([]),
    [error, setError] = useState(''),
    [connection, setConnection] = useState('Connecting'),
    [prompt, setPrompt] = useState(''),
    [attachments, setAttachments] = useState<Attachment[]>([]),
    [modal, setModal] = useState(''),
    [search, setSearch] = useState(''),
    [pin, setPin] = useState(''),
    [showContext, setShowContext] = useState(() => window.innerWidth > 1000),
    [showSessions, setShowSessions] = useState(false),
    [sending, setSending] = useState(false),
    [voice, setVoice] = useState(false),
    [newMessages, setNewMessages] = useState(false),
    [job, setJob] = useState<Data>({});
  const scroll = useRef<HTMLDivElement>(null),
    fileInput = useRef<HTMLInputElement>(null),
    textarea = useRef<HTMLTextAreaElement>(null),
    nearBottom = useRef(true),
    recognizer = useRef<any>(null),
    selectedRef = useRef(selected);
  selectedRef.current = selected;
  const report = (e: any) => setError(String(e).replace(/^Error: /, ''));
  const openSettings = async () => {
    try {
      const settings = await api('/settings');
      setBootstrap((b) => ({ ...b, settings }));
      setError('');
      setModal('settings');
    } catch (e) {
      report(e);
    }
  };
  const refreshSessions = useCallback(() => api('/sessions').then(setSessions).catch(report), []);
  const select = useCallback(async (id: string) => {
    try {
      const result = await api('/sessions/' + id);
      setSelected(id);
      setView(result);
      setEvents(result.events || []);
      setShowSessions(false);
      setPrompt('');
      setAttachments([]);
      nearBottom.current = true;
    } catch (e) {
      report(e);
    }
  }, []);
  const newSession = async () => {
    try {
      const result = await api('/sessions', 'POST', {});
      setSelected(result.id);
      setView(result);
      setEvents(result.events || []);
      setPrompt('');
      setAttachments([]);
      setShowSessions(false);
      nearBottom.current = true;
      refreshSessions();
    } catch (e) {
      report(e);
    }
  };
  useEffect(() => {
    let alive = true;
    (async () => {
      const fragment = new URLSearchParams(location.hash.slice(1));
      const token = fragment.get('token');
      if (token) {
        await api('/login', 'POST', { token });
        history.replaceState(null, '', location.pathname);
      }
      const data = await api('/bootstrap');
      if (!alive) return;
      setBootstrap(data);
      setSessions(data.sessions);
      if (data.sessions[0]) await select(data.sessions[0].id);
      else {
        const result = await api('/sessions', 'POST', {});
        if (alive) {
          setSelected(result.id);
          setView(result);
          setEvents(result.events || []);
          refreshSessions();
        }
      }
    })().catch(report);
    return () => {
      alive = false;
      recognizer.current?.abort();
    };
  }, [select, refreshSessions]);
  useEffect(() => {
    if (!selected) return;
    let socket: WebSocket,
      closed = false,
      timer: ReturnType<typeof setTimeout>,
      retry = 500;
    const connect = () => {
      setConnection('Connecting');
      socket = new WebSocket(
        `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/sessions/${selected}/events`,
      );
      socket.onopen = () => {
        retry = 500;
        setConnection('Connected');
      };
      socket.onmessage = ({ data }) => {
        const event = JSON.parse(data);
        if (event.type === 'snapshot') {
          setView(event.data);
          setEvents(event.data.events || []);
        } else if (event.type === 'metadata') {
          setView((v) => ({ ...v, ...event.data, state: { ...v?.state, ...event.data.state } }));
        } else if (event.type !== 'heartbeat') {
          setEvents((es) => mergeEvent(es, event));
          if (event.type === 'approval_pending')
            setView((v) =>
              v
                ? {
                    ...v,
                    pending: [
                      ...(v.pending || []).filter(
                        (p: Data) => p.request_id !== event.data.request_id,
                      ),
                      event.data,
                    ],
                  }
                : v,
            );
          if (event.type === 'approval_closed')
            setView((v) =>
              v
                ? {
                    ...v,
                    pending: (v.pending || []).filter(
                      (p: Data) => p.request_id !== event.data.request_id,
                    ),
                  }
                : v,
            );
          if (event.type === 'idle') {
            setView((v) => (v ? { ...v, busy: false } : v));
            refreshSessions();
          }
        }
      };
      socket.onclose = () => {
        if (!closed) {
          setConnection('Reconnecting');
          timer = setTimeout(connect, retry);
          retry = Math.min(retry * 2, 10000);
        }
      };
      socket.onerror = () => socket.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [selected, refreshSessions]);
  useEffect(() => {
    if (nearBottom.current) {
      scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'instant' });
      setNewMessages(false);
    } else setNewMessages(true);
  }, [events, view?.pending]);
  useEffect(() => {
    const id = setInterval(refreshSessions, 7000);
    return () => clearInterval(id);
  }, [refreshSessions]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        openSettings();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        newSession();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);
  const update = async (body: Data) => {
    if (!selected) return;
    try {
      const r = await api('/sessions/' + selected, 'PATCH', body);
      setView(r);
    } catch (e) {
      report(e);
    }
  };
  const run = async (action: string, data: Data = {}) => {
    try {
      setError('');
      await api(`/sessions/${selected}/actions`, 'POST', { action, data });
      setView((v) => (v ? { ...v, busy: true } : v));
    } catch (e) {
      report(e);
    }
  };
  const send = async () => {
    if (!prompt.trim() || sending || view?.busy || !view?.owned) return;
    setSending(true);
    try {
      await api(`/sessions/${selected}/actions`, 'POST', {
        action: 'prompt',
        data: { prompt, images: attachments.map(({ media_type, data }) => ({ media_type, data })) },
      });
      setView((v) => (v ? { ...v, busy: true } : v));
      setPrompt('');
      setAttachments([]);
      nearBottom.current = true;
      setError('');
    } catch (e) {
      report(e);
    } finally {
      setSending(false);
    }
  };
  const decide = async (id: string, decision: string) => {
    try {
      await api(`/sessions/${selected}/approvals`, 'POST', { request_id: id, decision });
      setView((v) =>
        v ? { ...v, pending: v.pending.filter((p: Data) => p.request_id !== id) } : v,
      );
    } catch (e) {
      report(e);
    }
  };
  const addFiles = async (files: FileList | File[]) => {
    if (!view?.vision) {
      report('Select a vision-capable model and enable vision in its profile first.');
      return;
    }
    try {
      const added: Attachment[] = [];
      for (const file of Array.from(files)) {
        if (
          !['image/png', 'image/jpeg', 'image/webp'].includes(file.type) ||
          file.size > 2 * 1024 * 1024
        )
          throw Error('Use PNG, JPEG, or WebP images up to 2 MiB each.');
        const data = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',')[1]);
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
        added.push({ name: file.name, media_type: file.type, data });
      }
      setAttachments((a) => {
        if (a.length + added.length > 4) {
          report('Attach at most four images.');
          return a;
        }
        return [...a, ...added];
      });
    } catch (e) {
      report(e);
    }
  };
  const startVoice = () => {
    const Speech = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!Speech) {
      setModal('');
      report('Voice input is unavailable in this browser. Use your system’s dictation shortcut.');
      return;
    }
    const r = new Speech();
    recognizer.current = r;
    r.lang = navigator.language;
    r.interimResults = false;
    r.continuous = false;
    r.onresult = (e: any) =>
      setPrompt((p) =>
        (
          p +
          ' ' +
          Array.from(e.results)
            .map((x: any) => x[0].transcript)
            .join(' ')
        ).trim(),
      );
    r.onerror = (e: any) => {
      report('Voice input: ' + e.error);
      setVoice(false);
    };
    r.onend = () => setVoice(false);
    try {
      r.start();
      setVoice(true);
      setModal('');
    } catch (e) {
      report(e);
    }
  };
  const ctx = view?.context || {},
    usage = view?.state?.usage || {},
    editable = !!view?.owned && !view?.busy,
    model = view?.state?.model || bootstrap?.settings.default_model || 'Choose model',
    models = bootstrap?.settings.models || [],
    activeEvents = events.some((e) =>
      ['turn_started', 'text_delta', 'error', 'action_result', 'history_restored'].includes(e.type),
    ),
    fraction = ctx.fraction_with_output || 0,
    project = (view?.workspace || bootstrap?.workspace || 'Workspace').split('/').at(-1);
  if (!bootstrap)
    return (
      <div className="connection-screen">
        <img src="/brand/dragon_cli.png" alt="Smok" />
        <h1>{error ? 'Connect to Smok' : 'Waking the dragon…'}</h1>
        <p>{error || 'Opening your workspace.'}</p>
        {error && (
          <p className="muted">
            Use the launch link printed by <code>smok --gui</code>.
          </p>
        )}
      </div>
    );
  return (
    <div className={'app-shell ' + (!showContext ? 'context-hidden' : '')}>
      <aside className={'sidebar ' + (showSessions ? 'mobile-open' : '')}>
        <div className="brand">
          <img src="/brand/dragon_cli.png" alt="" />
          <span>
            smok<span className="brand-dot">.</span>
          </span>
          <span className="version">{version}</span>
          <Button
            className="mobile-only"
            variant="ghost"
            size="icon"
            aria-label="Close sessions"
            onClick={() => setShowSessions(false)}
          >
            <X size={16} />
          </Button>
        </div>
        <div className="workspace-label">
          <Folder size={14} />
          <span title={bootstrap.workspace}>{bootstrap.workspace.split('/').at(-1)}</span>
          <span className="local-dot" title="Local workspace" />
        </div>
        <Button className="new-session" variant="outline" onClick={newSession}>
          <Plus size={17} />
          New session
        </Button>
        <label className="search">
          <Search size={14} />
          <input
            aria-label="Search sessions"
            placeholder="Find a session…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <div className="section-label">
          SESSIONS <span>{sessions.length}</span>
        </div>
        <nav className="session-list" aria-label="Sessions">
          {sessions
            .filter((s) => (s.title + ' ' + s.id).toLowerCase().includes(search.toLowerCase()))
            .map((s) => (
              <button
                key={s.id}
                className={'session-row ' + (selected === s.id ? 'selected' : '')}
                onClick={() => select(s.id)}
              >
                {s.branch ? (
                  <GitBranch size={15} />
                ) : s.busy ? (
                  <span className="activity-dot" />
                ) : (
                  <span className="session-icon">›</span>
                )}
                <span>
                  <strong>{s.title}</strong>
                  <small>
                    {s.model?.split('/').slice(1).join('/') || 'New conversation'}
                    {s.owned ? '' : ' · watch'}
                  </small>
                </span>
              </button>
            ))}
        </nav>
        <div className="section-label activity-label">BACKGROUND ACTIVITY</div>
        <div className="background-list">
          {(view?.workers || []).slice(-5).map((w: Data) => (
            <div className="worker-row" key={w.id}>
              <span className={w.status === 'running' ? 'activity-dot' : 'local-dot'} />
              <span>
                {w.role || 'Worker'}
                <small>{w.model}</small>
              </span>
              <em>{w.status}</em>
            </div>
          ))}
          {(view?.team?.runs || []).slice(0, 5).map((r: Data) => (
            <details key={r.id}>
              <summary>
                <GitBranch size={13} />
                {r.kind || 'Team run'}
                <span>{r.status || 'Saved'}</span>
              </summary>
              <pre>{JSON.stringify(r, null, 2)}</pre>
            </details>
          ))}
          {(view?.jobs?.jobs || []).map((j: Data) => (
            <div className="job-row" key={j.id}>
              <Terminal size={13} />
              <span title={j.command}>
                {j.command}
                <small>
                  {j.status} ·{' '}
                  <button
                    onClick={() =>
                      api(`/sessions/${selected}/jobs/${j.id}`)
                        .then((r) => {
                          setJob(r);
                          setModal('job');
                        })
                        .catch(report)
                    }
                  >
                    Output
                  </button>
                </small>
              </span>
              {j.status === 'running' && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Stop background process"
                  disabled={!editable}
                  onClick={() => run('stop_process', { id: j.id })}
                >
                  <Square size={12} />
                </Button>
              )}
            </div>
          ))}
          {!(view?.team?.runs?.length || view?.jobs?.jobs?.length || view?.workers?.length) && (
            <p className="empty-activity">Council, workers, and background jobs appear here.</p>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="connection-status">
            <span className={connection === 'Connected' ? 'local-dot' : 'offline-dot'} />
            {connection}
            <span>LOCAL APP</span>
          </div>
          <Button
            variant="ghost"
            onClick={() => {
              setShowSessions(false);
              setModal('setup');
            }}
          >
            <ShieldCheck size={16} />
            Setup checks
          </Button>
          <Button aria-label="Settings" variant="ghost" onClick={openSettings}>
            <Settings2 size={16} />
            Settings<span className="shortcut">⌘ ,</span>
          </Button>
        </div>
      </aside>
      <main className="main-panel">
        <header className="topbar">
          <Button
            className="mobile-only"
            variant="ghost"
            size="icon"
            aria-label="Open sessions"
            onClick={() => setShowSessions(true)}
          >
            <Menu size={18} />
          </Button>
          <div className="session-heading">
            <span className="workspace-breadcrumb">
              {project} <span>/</span>
            </span>
            <h1>{view?.title || 'New session'}</h1>
          </div>
          <div className="top-actions">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Release session"
              title="Release this session and stop its background processes; keep the history"
              disabled={!editable}
              onClick={() =>
                api(`/sessions/${selected}`, 'DELETE')
                  .then(() => api('/sessions/' + selected))
                  .then((r) => {
                    setView(r);
                    refreshSessions();
                  })
                  .catch(report)
              }
            >
              <Unplug size={16} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Share session"
              disabled={!selected || view?.busy}
              onClick={() => setModal('share')}
            >
              <Share2 size={17} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Toggle context panel"
              onClick={() => setShowContext(!showContext)}
            >
              {showContext ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
            </Button>
          </div>
        </header>
        <div className="session-toolbar">
          <div className="mode-switch" aria-label="Agent mode">
            <button
              disabled={!editable}
              className={view?.state?.mode === 'build' ? 'active' : ''}
              onClick={() => update({ mode: 'build' })}
            >
              <Wrench size={13} />
              Build
            </button>
            <button
              disabled={!editable}
              className={view?.state?.mode === 'plan' ? 'active' : ''}
              onClick={() => update({ mode: 'plan' })}
            >
              Plan
            </button>
          </div>
          <div className="model-picker">
            <span className="local-dot" />
            <select
              aria-label="Active model"
              disabled={!editable}
              value={model}
              onChange={(e) => update({ model: e.target.value })}
            >
              {!models.some((m: Data) => m.name === model) && (
                <option value={model}>{model}</option>
              )}
              {models.map((m: Data) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
            <ChevronDown size={13} />
          </div>
          <span className="toolbar-cost">
            <Coins size={14} />
            {money(usage.known_cost_usd)}
            {usage.unpriced_requests ? ' + unpriced' : ''}
          </span>
        </div>
        {error && (
          <div className="toast-error" role="alert">
            <CircleAlert size={16} />
            <span>{error}</span>
            <Button
              size="icon"
              variant="ghost"
              aria-label="Dismiss error"
              onClick={() => setError('')}
            >
              <X size={15} />
            </Button>
          </div>
        )}
        {!view?.owned && selected && (
          <div className="watch-banner">
            <div>
              <History size={15} />
              <span>Watching a saved or CLI session. Updates arrive live.</span>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                api('/sessions', 'POST', { resume: selected })
                  .then((r) => {
                    setView(r);
                    setEvents(r.events || []);
                    setSelected('');
                    setTimeout(() => setSelected(r.id), 0);
                    refreshSessions();
                  })
                  .catch(report)
              }
            >
              Resume here
            </Button>
          </div>
        )}
        <div
          ref={scroll}
          className="chat-scroll"
          onScroll={() => {
            const e = scroll.current!;
            nearBottom.current = e.scrollHeight - e.scrollTop - e.clientHeight < 100;
            if (nearBottom.current) setNewMessages(false);
          }}
        >
          <div className="chat-content">
            {!activeEvents ? (
              <div className="welcome">
                <div className="mascot-halo">
                  <img
                    src="/brand/dragon_mascot_512.png"
                    alt="Smok, your pixel dragon coding companion"
                  />
                </div>
                <div className="eyebrow">A LITTLE FIRE. A LOT OF FOCUS.</div>
                <h2>What are we building?</h2>
                <p>
                  Your workspace, your models, your next idea.
                  <br />
                  Let’s turn it into something that works.
                </p>
                <Button
                  className="welcome-setup"
                  variant="outline"
                  onClick={() => setModal('setup')}
                >
                  <ShieldCheck size={15} />
                  Check setup
                </Button>
                <div className="starter-grid">
                  {[
                    [
                      'Explore this project',
                      'Find the important pieces.',
                      'Inspect this repository and explain its architecture and main entry points.',
                    ],
                    [
                      'Plan a change',
                      'Think it through together.',
                      'Help me plan the next useful improvement to this project. Inspect it first.',
                    ],
                    [
                      'Review my changes',
                      'A fresh pair of dragon eyes.',
                      'Review the current changes for bugs and missing tests.',
                    ],
                  ].map(([title, subtitle, text], i) => (
                    <button
                      key={title}
                      onClick={() => {
                        setPrompt(text);
                        if (i !== 2) update({ mode: 'plan' });
                        textarea.current?.focus();
                      }}
                    >
                      <span className="starter-icon">
                        {i === 0 ? (
                          <Search size={17} />
                        ) : i === 1 ? (
                          <GitBranch size={17} />
                        ) : (
                          <ShieldCheck size={17} />
                        )}
                      </span>
                      <strong>{title}</strong>
                      <span>{subtitle}</span>
                      <ArrowUp size={15} />
                    </button>
                  ))}
                </div>
                <div className="welcome-footnote">
                  <ShieldCheck size={13} />
                  Changes and commands follow your permission rules.
                </div>
              </div>
            ) : (
              <Transcript
                events={events}
                pending={view?.pending || []}
                decide={decide}
                disabled={connection !== 'Connected'}
              />
            )}{' '}
            {view?.busy && !view?.pending?.length && (
              <div className="working">
                <span className="activity-dot" />
                Smok is working<span className="working-dots">…</span>
              </div>
            )}
          </div>
        </div>
        {newMessages && (
          <Button
            className="jump-latest"
            variant="outline"
            size="sm"
            onClick={() => {
              nearBottom.current = true;
              scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' });
              setNewMessages(false);
            }}
          >
            <ArrowDown size={14} />
            Jump to latest
          </Button>
        )}
        <div className="composer-area">
          <div
            className={'composer ' + (voice ? 'listening' : '')}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              addFiles(e.dataTransfer.files);
            }}
          >
            {attachments.length > 0 && (
              <div className="attachments">
                {attachments.map((a, i) => (
                  <div key={i}>
                    <img src={`data:${a.media_type};base64,${a.data}`} alt={a.name} />
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={'Remove ' + a.name}
                      onClick={() => setAttachments(attachments.filter((_, j) => j !== i))}
                    >
                      <X size={12} />
                    </Button>
                    <span>{a.name}</span>
                  </div>
                ))}
              </div>
            )}
            <textarea
              ref={textarea}
              aria-label="Message Smok"
              value={prompt}
              disabled={!view?.owned}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={
                view?.owned
                  ? 'Ask Smok to build, fix, or explore…'
                  : 'Resume this session to continue the conversation.'
              }
              onKeyDown={(e) => {
                if (
                  e.key === 'Enter' &&
                  !e.shiftKey &&
                  !e.metaKey &&
                  !e.ctrlKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <div className="composer-controls">
              <input
                hidden
                ref={fileInput}
                type="file"
                multiple
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  if (e.target.files) addFiles(e.target.files);
                  e.target.value = '';
                }}
              />
              <div className="composer-tools">
                <Button
                  variant="ghost"
                  size="icon"
                  disabled={!editable}
                  aria-label="Attach images"
                  title={
                    view?.vision
                      ? 'Attach images (or drag and drop)'
                      : 'Requires a vision-enabled model profile'
                  }
                  onClick={() => fileInput.current?.click()}
                >
                  <ImagePlus size={17} />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  disabled={!editable}
                  aria-label={voice ? 'Stop dictation' : 'Voice input'}
                  onClick={() => (voice ? recognizer.current?.stop() : setModal('voice'))}
                >
                  <Mic size={17} />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={!editable}
                  onClick={() => setModal('tools')}
                >
                  <Sparkles size={14} />
                  Tools
                </Button>
              </div>
              <div className="send-controls">
                <span>
                  {voice ? 'Listening… review text before sending' : '↵ send · ⇧ ↵ newline'}
                </span>
                {view?.busy ? (
                  <Button
                    size="icon"
                    variant="outline"
                    aria-label="Stop turn"
                    onClick={() => api(`/sessions/${selected}/stop`, 'POST', {}).catch(report)}
                  >
                    <Square size={16} />
                  </Button>
                ) : (
                  <Button
                    size="icon"
                    aria-label="Send message"
                    disabled={!prompt.trim() || !editable || sending}
                    onClick={send}
                  >
                    <ArrowUp size={18} />
                  </Button>
                )}
              </div>
            </div>
          </div>
          <div className="composer-footer">
            <ShieldCheck size={12} />
            <select
              aria-label="Session permission mode"
              disabled={!editable}
              value={view?.permissions || 'ask'}
              onChange={(e) => update({ permissions: e.target.value })}
            >
              <option value="ask">Ask before changes</option>
              <option value="auto-edit">Auto-edit · ask for commands</option>
              <option value="full-auto">Full auto</option>
            </select>
            <span>Smok can make mistakes. Review the diff.</span>
          </div>
        </div>
      </main>
      {modal === 'setup' && (
        <SetupDialog model={model} onClose={() => setModal('')} onSettings={openSettings} />
      )}
      {showContext && (
        <aside className="context-panel">
          <header>
            <span>WORKSPACE CONTEXT</span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Close context panel"
              onClick={() => setShowContext(false)}
            >
              <X size={14} />
            </Button>
          </header>
          <section>
            <div className="row-between">
              <h2>Context window</h2>
              <span className="pill">
                {ctx.source === 'provider_count' ? 'COUNTED' : 'ESTIMATE'}
              </span>
            </div>
            <div className="context-number">
              {number(ctx.input_tokens)}
              <span> / {number(ctx.working_context_limit)} tokens</span>
            </div>
            <div
              className="context-meter"
              aria-label={'Context ' + Math.round(fraction * 100) + ' percent'}
            >
              {Object.entries(ctx.breakdown_estimated_tokens || {}).map(([key, value], i) => (
                <span
                  key={key}
                  title={key}
                  style={{
                    width:
                      Math.max(0, (+String(value) / (ctx.working_context_limit || 32768)) * 100) +
                      '%',
                    background: [
                      '#E8562A',
                      '#C68C6B',
                      '#7D8D81',
                      '#9A86A8',
                      '#BD9F78',
                      '#D9C4B4',
                      '#67656E',
                      '#99B5B7',
                    ][i % 8],
                  }}
                />
              ))}
            </div>
            <div className="context-caption">
              {Math.round(fraction * 100)}% with output allowance
            </div>
            <div className="context-breakdown">
              {Object.entries(ctx.breakdown_estimated_tokens || {})
                .filter(([, n]) => Number(n) > 0)
                .map(([k, n]) => (
                  <div key={k}>
                    <span>{k.replaceAll('_', ' ')}</span>
                    <span>{number(Number(n))}</span>
                  </div>
                ))}
            </div>
            <Button
              variant="ghost"
              className="text-button"
              size="sm"
              disabled={!editable || !events.length}
              onClick={() => run('compact')}
            >
              Compact context <ArrowUp size={12} />
            </Button>
          </section>
          <section>
            <div className="row-between">
              <h2>Pinned files</h2>
              <Pin size={14} />
            </div>
            {(ctx.pinned_files || []).map((p: string) => (
              <div className="pin-row" key={p}>
                <code>{p}</code>
                <button
                  disabled={!editable}
                  aria-label={'Drop ' + p}
                  onClick={() =>
                    api(`/sessions/${selected}/context`, 'POST', { action: 'drop', target: p })
                      .then(setView)
                      .catch(report)
                  }
                >
                  <X size={13} />
                </button>
              </div>
            ))}
            {!ctx.pinned_files?.length && (
              <p className="muted small">Keep essential files in every turn.</p>
            )}
            <form
              className="pin-form"
              onSubmit={(e) => {
                e.preventDefault();
                api(`/sessions/${selected}/context`, 'POST', { action: 'pin', target: pin })
                  .then((r) => {
                    setView(r);
                    setPin('');
                  })
                  .catch(report);
              }}
            >
              <input
                aria-label="Pin file path"
                placeholder="path/to/file"
                value={pin}
                onChange={(e) => setPin(e.target.value)}
              />
              <Button
                size="icon"
                variant="outline"
                aria-label="Pin file"
                disabled={!editable || !pin}
              >
                <Plus size={14} />
              </Button>
            </form>
            <details className="context-groups">
              <summary>
                History groups <span>{ctx.groups?.length || 0}</span>
              </summary>
              {(ctx.groups || []).slice(-30).map((g: Data) => (
                <div key={g.id}>
                  <span>
                    {g.id} · {number(g.estimated_tokens)} tokens
                  </span>
                  <button
                    disabled={!editable}
                    aria-label={'Drop ' + g.id}
                    onClick={() =>
                      api(`/sessions/${selected}/context`, 'POST', { action: 'drop', target: g.id })
                        .then(setView)
                        .catch(report)
                    }
                  >
                    Drop
                  </button>
                </div>
              ))}
            </details>
          </section>
          <section>
            <div className="row-between">
              <h2>Model routing</h2>
              <Zap size={14} />
            </div>
            <div className="routing-row">
              <span className="local-dot" />
              <span>{model.split('/').slice(1).join('/')}</span>
              <span className="small muted">ACTIVE</span>
            </div>
            {(view?.team?.ladder || []).map((m: string, i: number) => (
              <div className="ladder-row" key={m}>
                {i + 1}
                <span>{m}</span>
              </div>
            ))}
            {!view?.team?.ladder?.length && (
              <p className="muted small">
                Using the selected model. Role routes follow your team configuration.
              </p>
            )}
          </section>
          <section>
            <div className="row-between">
              <h2>Checkpoints</h2>
              <History size={14} />
            </div>
            {(view?.checkpoints || [])
              .slice(-6)
              .reverse()
              .map((c: Data) => (
                <div className="checkpoint" key={c.id}>
                  <div>
                    <span className="checkpoint-dot" />
                    <strong>Checkpoint {c.id}</strong>
                    <span>
                      {c.undone
                        ? 'Undone'
                        : c.abandoned
                          ? 'Interrupted'
                          : c.changes.length + ' files'}
                    </span>
                  </div>
                  <div className="checkpoint-actions">
                    <button
                      disabled={!editable || c.undone || c.abandoned}
                      onClick={() => run('restore', { checkpoint: c.id })}
                    >
                      Restore
                    </button>
                    <button
                      disabled={!editable || c.abandoned}
                      onClick={() =>
                        api(`/sessions/${selected}/branch`, 'POST', { checkpoint: c.id })
                          .then((r) => {
                            setSelected(r.id);
                            setView(r);
                            setEvents(r.events || []);
                            refreshSessions();
                          })
                          .catch(report)
                      }
                    >
                      <GitBranch size={11} />
                      Branch
                    </button>
                  </div>
                </div>
              ))}
            {!view?.checkpoints?.length && (
              <p className="muted small">Your next turn starts a checkpoint.</p>
            )}
          </section>
          <section className="session-cost">
            <div className="row-between">
              <h2>Session usage</h2>
              <Coins size={14} />
            </div>
            <div className="cost-total">{money(usage.known_cost_usd)}</div>
            <div className="small muted">
              {usage.unpriced_requests
                ? `${usage.unpriced_requests} unpriced requests · total incomplete`
                : 'Recorded API cost · configured prices'}
            </div>
            <div className="usage-grid">
              <div>
                <strong>{number(usage.input_tokens)}</strong>
                <span>Input tokens</span>
              </div>
              <div>
                <strong>{number(usage.output_tokens)}</strong>
                <span>Output tokens</span>
              </div>
            </div>
            <div className="small muted">
              {usage.requests || 0} requests · {usage.estimated_requests || 0} estimated
            </div>
            <details className="context-groups">
              <summary>Next request estimate</summary>
              {(view?.estimates || []).map((m: Data) => (
                <div key={m.model}>
                  <span>{m.model}</span>
                  <strong>
                    {m.estimated_request_usd === null ? 'Unpriced' : money(m.estimated_request_usd)}
                  </strong>
                </div>
              ))}
            </details>
            <Button
              variant="ghost"
              size="sm"
              className="text-button"
              disabled={!editable}
              onClick={() => setModal('budget')}
            >
              Set run budget
            </Button>
          </section>
          <div className="context-brand">
            Small dragon. Serious work.
            <img src="/brand/dragon_cli.png" alt="" />
          </div>
        </aside>
      )}
      {modal === 'job' && (
        <Dialog
          open
          onOpenChange={() => setModal('')}
          title="Background output"
          description={job.command}
        >
          <div className="settings-body">
            <pre>{job.output || '[No output yet]'}</pre>
            <p className="muted small">
              {job.status} · {job.lost_bytes || 0} older bytes unavailable
            </p>
            <Button
              variant="outline"
              onClick={() =>
                api(
                  `/sessions/${selected}/jobs/${job.id}?offset=${Math.max(0, (job.total || 0) - 12000)}`,
                )
                  .then(setJob)
                  .catch(report)
              }
            >
              Refresh latest output
            </Button>
          </div>
        </Dialog>
      )}
      {modal === 'settings' && (
        <Settings
          settings={bootstrap.settings}
          onClose={() => setModal('')}
          onSaved={(s) => {
            setBootstrap({ ...bootstrap, settings: s });
            if (selected)
              api('/sessions/' + selected)
                .then(setView)
                .catch(report);
          }}
          onError={report}
        />
      )}
      {modal === 'share' && (
        <ShareDialog id={selected} onClose={() => setModal('')} onError={report} />
      )}
      {modal === 'tools' && view && (
        <Workflows view={view} models={models} onClose={() => setModal('')} run={run} />
      )}
      {modal === 'voice' && (
        <Dialog
          open
          onOpenChange={() => setModal('')}
          title="Voice input"
          description="Speak, then review your words in the composer."
        >
          <p className="dialog-copy">
            Your browser may use an online speech service to transcribe audio. Smok sends only the
            text you choose to submit to your selected model. Browser and microphone support vary.
          </p>
          <div className="dialog-footer">
            <Button variant="ghost" onClick={() => setModal('')}>
              Cancel
            </Button>
            <Button onClick={startVoice}>
              <Mic size={16} />
              Start dictation
            </Button>
          </div>
        </Dialog>
      )}
      {modal === 'budget' && (
        <Budget limits={view?.limits} onClose={() => setModal('')} save={update} />
      )}
    </div>
  );
}
function Budget({
  limits,
  onClose,
  save,
}: {
  limits?: Data;
  onClose: () => void;
  save: (d: Data) => void;
}) {
  const [tokens, setTokens] = useState(String(limits?.budget_tokens ?? '')),
    [dollars, setDollars] = useState(String(limits?.budget_usd ?? '')),
    [iterations, setIterations] = useState(String(limits?.max_iterations ?? 12)),
    [timeout, setTimeout] = useState(String(limits?.turn_timeout ?? ''));
  return (
    <Dialog
      open
      onOpenChange={onClose}
      title="Run budget"
      description="Limits cover this open session and its workers. Recorded usage is not reset."
    >
      <div className="settings-body">
        <label>
          Token cap (blank for no cap)
          <input type="number" min="1" value={tokens} onChange={(e) => setTokens(e.target.value)} />
        </label>
        <label>
          Dollar cap (requires configured prices)
          <input
            type="number"
            min="0.01"
            step="0.01"
            value={dollars}
            onChange={(e) => setDollars(e.target.value)}
          />
        </label>
        <label>
          Model calls per turn
          <input
            type="number"
            min="1"
            max="40"
            value={iterations}
            onChange={(e) => setIterations(e.target.value)}
          />
        </label>
        <label>
          Turn time limit in seconds (blank for no limit)
          <input
            aria-label="Turn time limit in seconds"
            type="number"
            min="1"
            max="86400"
            value={timeout}
            onChange={(e) => setTimeout(e.target.value)}
          />
          <span className="small muted">
            Includes approval waits and model routing. Partial work is retained when time runs out.
          </span>
        </label>
      </div>
      <div className="dialog-footer">
        <Button
          onClick={() => {
            save({
              budget_tokens: tokens ? +tokens : null,
              budget_usd: dollars ? +dollars : null,
              max_iterations: +iterations,
              turn_timeout: timeout ? +timeout : null,
            });
            onClose();
          }}
        >
          Set limits
        </Button>
      </div>
    </Dialog>
  );
}
