import React, { useMemo, useState } from 'react';

const Hint = ({ children }) => <p className="text-xs text-slate-400 mt-1">{children}</p>;
const Label = ({ htmlFor, children }) => <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-200">{children}</label>;
const Input = ({ id, ...props }) => <input id={id} className="mt-1 w-full rounded-xl bg-slate-800/60 border border-slate-700 px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-400" {...props} />;
const Button = ({ variant = 'primary', className = '', ...props }) => {
  const base = 'inline-flex items-center justify-center rounded-xl px-4 py-2 text-sm font-semibold transition active:scale-[.98] ';
  const variants = { primary: 'bg-indigo-500 hover:bg-indigo-400 text-white shadow-md shadow-indigo-900/30', secondary: 'bg-red-500 hover:bg-red-400 text-white shadow-md shadow-red-900/30', ghost: 'bg-transparent hover:bg-slate-800/60 text-slate-200 border border-slate-700' };
  return <button className={`${base}${variants[variant]} ${className}`} {...props} />;
};
const Chip = ({ status }) => {
  const color = status === 'Running' ? 'bg-emerald-500/20 text-emerald-300 border-emerald-400/40' : status === 'Pending' || status === 'ContainerCreating' ? 'bg-amber-500/20 text-amber-300 border-amber-400/40' : status ? 'bg-rose-500/20 text-rose-300 border-rose-400/40' : 'bg-slate-700 text-slate-300 border-slate-600';
  return (<span className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs ${color}`}><span className="h-2 w-2 rounded-full bg-current/60" />{status || 'Unknown'}</span>);
};
// const copy = async (text) => {
//   try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
// };
// const pfCmd = (ns) => `kubectl port-forward -n ${ns} pod/${ns}-pod 8001:8000`;




export default function App() {
  const [apiBase] = useState('http://127.0.0.1:8000');
  const [name, setName] = useState('');
  const [cpu, setCpu] = useState(0.25);
  const [memory, setMemory] = useState(256);
  const [storage, setStorage] = useState(1);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState([]);
  const [adminOpen, setAdminOpen] = useState(false);
  const [adminPwd, setAdminPwd] = useState('');
  const [isAuthed, setIsAuthed] = useState(false);
  const [students, setStudents] = useState([]);
  const [statusName, setStatusName] = useState('');
  const [specificStatus, setSpecificStatus] = useState('');
  const appendLog = (entry) => setLog((prev) => [{ t: new Date().toLocaleTimeString(), ...entry }, ...prev].slice(0, 50));
  const payload = useMemo(() => ({ name, cpu: Number(cpu), memory: Number(memory), storage: Number(storage) }), [name, cpu, memory, storage]);
  const call = async (path, init) => {
    setBusy(true);
    try {
      const res = await fetch(`${apiBase}${path}`, init);
      const txt = await res.text();
      let data; try { data = JSON.parse(txt); } catch { data = txt; }
      let okStatus = res.ok;
if (typeof data === 'object' && data.status) {
  const stat = data.status.toLowerCase();
  if (stat === 'running') okStatus = 'Running';
  else if (stat === 'pending' || stat === 'containercreating') okStatus = 'Pending';
  else if (stat === 'not found' || stat === 'error') okStatus = 'Fail';
}
if (typeof data === 'object' && data && data.status) {
  const stat = String(data.status).toLowerCase();
  if (stat === 'running') okStatus = 'Running';
  else if (stat === 'pending' || stat === 'containercreating') okStatus = 'Pending';
  else if (stat === 'not found' || stat === 'error') okStatus = 'Fail';
}
// normalize booleans to labels
if (okStatus === true) okStatus = 'OK';
if (okStatus === false) okStatus = 'Fail';
// if /deploy succeeded but no status yet, treat as Pending
if (path.startsWith('/deploy') && okStatus === 'OK' && !(data && data.status)) {
  okStatus = 'Pending';
}
// Filter out last_error from data before logging
const logData = typeof data === 'object' && data !== null 
  ? Object.fromEntries(Object.entries(data).filter(([key]) => key !== 'last_error'))
  : data;
appendLog({ path, ok: okStatus, data: logData });

      // If response is not ok (4xx, 5xx), throw error to stop execution
      if (!res.ok) {
        throw new Error('API_ERROR'); // Special marker to avoid duplicate logging
      }

      return data;
    } catch (e) {
      // Only log if it's not already logged (network errors, etc)
      if (e.message !== 'API_ERROR') {
        appendLog({ path, ok: false, data: String(e) });
      }
      throw e;
    } finally {
      setBusy(false);
    }
  };
  const adminCall = async (path, init = {}) => {
    const headers = { ...(init.headers || {}), 'x-admin-key': adminPwd };
    return call(path, { ...init, headers });
  };
  const delay = (ms) => new Promise((res) => setTimeout(res, ms));
  const waitForRunning = async (ns, maxAttempts = 30, intervalMs = 2000) => {
    for (let i = 0; i < maxAttempts; i++) {
      const data = await call(`/status?name=${encodeURIComponent(ns)}`);
      const phase = data && data.status;
      if (phase === 'Running') {
        setStatus('Running');
        appendLog({ path: '/status', ok: 'Running', data: `${ns} pod is Running` });

        return true;
      }
      await delay(intervalMs);
    }
    appendLog({ path: '/status', ok: false, data: ` ${ns} ImagePullBackOff ` });
    return false;
  };
  const onDeploy = async () => {
    if (!name.trim()) {
      appendLog({
        path: '/submit',
        ok: false,
        data: 'Student name/namespace required before deployment.',
      });
      return;
    }
  
    // 1) Save request into MongoDB (with resource validation)
    try {
      await call('/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (e) {
      // Submit failed (likely insufficient resources), stop here
      return;
    }
  
    // 2) Ask backend to deploy using data from MongoDB
    try {
      await call(`/deploy-from-db?name=${encodeURIComponent(name)}`, {
        method: 'POST',
      });
    } catch (e) {
      // Deploy failed, stop here
      return;
    }
  
    // 3) Wait until pod is Running, to show in Activity Log + status chip
    await waitForRunning(name);
  };
  
  const checkSpecificStatus = async (ns) => {
    try { const data = await call(`/status?name=${encodeURIComponent(ns)}`); if (data && data.status) { setSpecificStatus(data.status); } else { setSpecificStatus('Not Found'); } } catch { setSpecificStatus('Error'); }
  };
  const onAdminLogin = async () => {
    try {
      const data = await adminCall('/admin/students');
      if (Array.isArray(data)) {
        setIsAuthed(true);
        setStudents(data);
        appendLog({ path: '/admin/login', ok: 'OK', data: 'Admin login successful' });
      } else {
        setIsAuthed(false);
        appendLog({ path: '/admin/login', ok: false, data: 'Login failed - invalid response' });
      }
    } catch (e) {
      setIsAuthed(false);
      appendLog({ path: '/admin/login', ok: false, data: 'Wrong password' });
    }
  };
  const refreshStudents = async () => { const data = await adminCall('/admin/students'); if (Array.isArray(data)) setStudents(data); };
  const onDeleteDeployment = async (studentName) => { await adminCall(`/cleanup?name=${encodeURIComponent(studentName)}`, { method: 'DELETE' }); await refreshStudents(); };
  const field = (s, a, b, c) => s?.[a] ?? s?.[b]?.[c] ?? '';

  // const onPortForward = async () => {
  //   if (!statusName.trim()) {
  //     appendLog({ path: '/portforward', ok: false, data: 'Namespace required' });
  //     return;
  //   }
  //   try {
  //     const data = await adminCall(`/portforward?name=${encodeURIComponent(statusName)}`, { method: 'POST' });
  //     if (data?.url) {
  //       appendLog({ path: '/portforward', ok: true ? 'OK' : 'Fail', data: `Forwarded → ${data.url}` });
  //       window.open(data.url, '_blank', 'noopener,noreferrer');
  //     } else {
  //       appendLog({ path: '/portforward', ok: false, data });
  //     }
  //   } catch (e) {
  //     appendLog({ path: '/portforward', ok: false, data: String(e) });
  //   }
  // };

  const pfStart = async (ns) => {
    const res = await fetch(`http://127.0.0.1:8000/pf/start?name=${encodeURIComponent(ns)}`, { method: 'POST' });
    return res.json();
  };
  
  
  const pfStopAll = async () => {
    const res = await fetch(`http://127.0.0.1:8000/pf/stop_all`, { method: 'POST' });
    const data = await res.json();
    return data;
  };
  
  

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-950 via-slate-950 to-slate-900 text-slate-100" style={{overscrollBehavior: 'none'}}>
      <header className="sticky top-0 z-20 bg-slate-950/80 backdrop-blur-md border-b border-blue-800/40">
  <nav className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between">
    {/* Left section */}
    <div className="flex items-center gap-4">
      <Button variant="ghost" onClick={() => setAdminOpen(true)}>Admin</Button>
    </div>

    {/* Center section (title) */}
    <div className="flex items-center gap-3">
      <div className="h-9 w-9 rounded-xl bg-blue-500/20 ring-1 ring-blue-400/30 grid place-items-center">
        <span className="text-blue-300 font-black text-lg">D</span>
      </div>
      <div className="text-center">
        <p className="text-sm uppercase tracking-widest text-blue-400">PodSphere</p>
        <h1 className="text-lg font-semibold text-slate-100">Your Pods. Your Space.</h1>
      </div>
    </div>

    {/* Right section */}
    <div className="flex items-center gap-3">
      <a
        href={apiBase}
        target="_blank"
        rel="noopener noreferrer"
        title="Open API in new tab"
        className="hidden md:inline-flex items-center rounded-full border border-slate-700 bg-slate-900/60 px-3 py-1 text-xs text-blue-300 hover:text-indigo-400 hover:border-indigo-400 transition"
      >
        {apiBase}
      </a>
    </div>
  </nav>
</header>



      <main className="mx-auto max-w-5xl px-4 py-8 grid gap-6 md:grid-cols-3">
        <section className="md:col-span-2">
          <div className="rounded-2xl border border-blue-800/30 bg-gradient-to-b from-slate-900/60 to-slate-950/80 p-5 shadow-xl shadow-black/20">
            <h2 className="text-base font-semibold text-slate-100">Student Configuration</h2>
            <p className="text-sm text-slate-400 mb-4">Provide inputs; the system converts numeric values into Kubernetes resource units (m, Mi, Gi).</p>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <Label htmlFor="name">Student Name / Namespace</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Type namespace" />
                <Hint>Manual typing required — namespace will be used as Kubernetes namespace,no spaces allowed</Hint>
              </div>
              <div>
                <Label htmlFor="cpu">CPU (cores)</Label>
                <Input id="cpu" type="number" step="0.05" min="0.05" value={cpu} onChange={(e) => setCpu(e.target.value)} placeholder="0.25" />
                <Hint>0.25 cores = 250m.</Hint>
              </div>
              <div>
                <Label htmlFor="memory">Memory (MiB)</Label>
                <Input id="memory" type="number" min="64" step="64" value={memory} onChange={(e) => setMemory(e.target.value)} placeholder="256" />
                <Hint>Example: 256 → 256Mi.</Hint>
              </div>
              <div>
                <Label htmlFor="storage">Storage (GiB)</Label>
                <Input id="storage" type="number" min="1" step="1" value={storage} onChange={(e) => setStorage(e.target.value)} placeholder="1" />
                <Hint>Future support for persistent volumes.</Hint>
              </div>
            </div>
            <div className="mt-6 flex flex-wrap gap-3">
              <Button onClick={onDeploy} disabled={busy}>Save & Deploy</Button>
              

            </div>
          </div>

          <section className="mt-8 rounded-2xl border border-blue-800/30 bg-gradient-to-b from-slate-900/60 to-slate-950/80 p-5 shadow-xl shadow-black/20">
            {/* <h2 className="text-base font-semibold text-slate-100 mb-2">Check Pod Status</h2> */}
            <p className="text-sm text-slate-400 mb-4">Enter a student name (namespace) to view their current pod status or to get the port-forward command.</p>
            <div className="mt-6 flex flex-col md:flex-row gap-3 items-center">
              <input className="flex-1 rounded-xl bg-slate-800/60 border border-slate-700 px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-400" placeholder="Enter student namespace" value={statusName} onChange={(e) => setStatusName(e.target.value)} />
              <Button onClick={() => checkSpecificStatus(statusName)} disabled={busy || !statusName.trim()}>Check Status</Button>
            </div>
            {specificStatus && (<div className="mt-4 text-sm text-slate-300"><p><span className="font-semibold">Namespace:</span> {statusName}</p><p><span className="font-semibold">Pod Status:</span> <Chip status={specificStatus} /></p></div>)}
            {specificStatus === 'Running' && (
  <div className="mt-4 space-y-2">
    <Button
  variant="primary"
  onClick={async () => {
    const ns = statusName.trim();
    if (!ns) return;

    const r = await pfStart(ns);

    appendLog({
      t: new Date().toLocaleTimeString(),
      path: '/pf/start',
      ok: r.status === 'forwarding' || r.status === 'already-forwarding'? 'OK' : 'FAIL',
      data: r
    });

    if (r.url) window.open(r.url, '_blank');
  }}
  disabled={busy || !statusName.trim()}
>
  Port-forward this pod & Open
</Button>

    {/* <Button
      onClick={async () => {
        const ok = await copy(pfCmd(statusName));
        appendLog({
          path: 'clipboard',
          ok: ok ? 'OK' : 'Fail',
          data: ok ? `${pfCmd(statusName)}` : 'Copy failed',
        });
      }}
    >
      Copy Port-Forward Command
    </Button> */}
    <div className="flex flex-wrap gap-2 mt-3">
  {/* <Button
    onClick={async () => {
      if (!statusName.trim()) return;
      const r = await pfStart(statusName.trim());
      // log like your other entries
      // ok when status === 'forwarding' else fail
      appendLog({
        t: new Date().toLocaleTimeString(),
        path: '/pf/start',
        ok: r.status === 'forwarding' || r.status === 'already-forwarding',
        data: r,
      });
      if (r.url) {
        try {
          await navigator.clipboard.writeText(`kubectl port-forward -n ${statusName.trim()} pod/${statusName.trim()}-pod ${r.local_port}:8000`);
        } catch {}
      }
    }}
  >
    Port-forward this pod
  </Button> */}

  <Button
    variant="primary"
    onClick={async () => {
      const r = await pfStopAll();
      appendLog({
        t: new Date().toLocaleTimeString(),
        path: '/pf/stop_all',
        ok: true?'OK':'Fail',
        data: r,
      });
    }}
  >
    Stop port forwards
  </Button>
</div>


    {/* <p className="text-xs text-slate-400">
      After running the above command, open:&nbsp;
      <a
        href="http://127.0.0.1:8001/"
        target="_blank"
        rel="noreferrer"
        className="text-indigo-300 underline"
      >
        http://127.0.0.1:8001/
      </a>
    </p> */}
  </div>
)}

          </section>
        </section>

        <aside className="md:col-span-1">
          <div className="rounded-2xl border border-blue-800/30 bg-slate-950 p-4 sticky top-20 max-h-[70vh] overflow-auto">
            <h3 className="text-sm font-semibold text-slate-200 mb-3">Activity Log</h3>
            <ul className="space-y-2">
              {log.length === 0 && <li className="text-sm text-slate-500">No activity yet. Use the buttons to interact with the API.</li>}
              {log.map((l, i) => (
                <li key={i} className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                  <div className="flex items-center justify-between text-xs text-slate-400"><span>{l.t}</span><span
  className={
    l.ok === 'Running' || l.ok === 'OK'
      ? 'text-emerald-300'
      : l.ok === 'Pending'
      ? 'text-amber-300'
      : 'text-rose-300'
  }
>
  {l.ok === 'Running'
    ? 'OK/Running'
    : l.ok === 'Pending'
    ? 'Pending/Processing'
    : l.ok === 'OK'
    ? 'OK'
    : 'FAIL'}
</span>
</div>
                  <div className="mt-1 text-xs text-slate-300"><pre className="whitespace-pre-wrap break-words">{
                    (() => {
                      try {
                        if (typeof l.data === 'string') {
                          return l.data;
                        }
                        if (l.data?.detail) {
                          // Handle nested detail objects
                          if (typeof l.data.detail === 'object') {
                            return l.data.detail.message || l.data.detail.error || JSON.stringify(l.data.detail, null, 2).replace(/[{}"]/g, '').trim();
                          }
                          return l.data.detail;
                        }
                        return JSON.stringify(l.data, null, 2).replace(/[{}"]/g, '').trim();
                      } catch (e) {
                        return 'Error displaying data';
                      }
                    })()
                  }</pre></div>
                </li>
              ))}
            </ul>
          </div>
        </aside>
      </main>

      {adminOpen && (
        <div className="fixed inset-0 z-20 bg-black/60" onClick={() => setAdminOpen(false)}>
          <div className="absolute left-0 top-0 h-full w-full max-w-xl bg-slate-950 border-r border-blue-800/30 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4"><h3 className="text-base font-semibold text-slate-100">Admin Panel</h3><Button variant="ghost" onClick={() => setAdminOpen(false)}>Close</Button></div>
            {!isAuthed ? (
              <div className="space-y-3">
                <Label htmlFor="pwd">Admin Password</Label>
                <Input 
                  id="pwd" 
                  type="password" 
                  value={adminPwd} 
                  onChange={(e) => setAdminPwd(e.target.value)} 
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && adminPwd.trim()) {
                      onAdminLogin();
                    }
                  }}
                  placeholder="Enter admin password" 
                />
                <div className="flex gap-2"><Button onClick={onAdminLogin} disabled={!adminPwd}>Login</Button></div>
                <Hint>Protected via header <code>x-admin-key</code> on backend.</Hint>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-200">Students in MongoDB</h4>
                  <div className="flex gap-2">
                    <Button variant="primary" onClick={refreshStudents}>Refresh</Button>
                    <Button variant="ghost" onClick={() => setIsAuthed(false)}>Logout</Button>
                  </div>
                </div>
                <div className="rounded-xl border border-slate-800 overflow-hidden overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-900/60 text-slate-300">
                      <tr>
                        <th className="px-3 py-2 text-left">Name</th>
                        <th className="px-3 py-2 text-left">CPU</th>
                        <th className="px-3 py-2 text-left">Memory</th>
                        <th className="px-3 py-2 text-left">Storage</th>
                        <th className="px-3 py-2 text-left">Status</th>
                        <th className="px-3 py-2 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {students.length === 0 && (<tr><td className="px-3 py-3 text-slate-500" colSpan={6}>No records found.</td></tr>)}
                      {students.map((s, idx) => {
                        const cpuRaw = field(s, 'cpu', 'input_numeric', 'cpu');
                        const memRaw = field(s, 'memory', 'input_numeric', 'memory_mb');
                        const stoRaw = field(s, 'storage', 'input_numeric', 'storage_gb');
                        const cpuK = field(s, 'cpu_k8s', 'k8s_resources', 'cpu');
                        const memK = field(s, 'memory_k8s', 'k8s_resources', 'memory');
                        const stoK = field(s, 'storage_k8s', 'k8s_resources', 'storage');
                        const livePhase = s.live_phase || 'Unknown';
                        return (
                          <tr key={idx} className="border-t border-slate-800">
                            <td className="px-3 py-2">{s.name}</td>
                            <td className="px-3 py-2">{cpuRaw} {cpuK ? `(${cpuK})` : ''}</td>
                            <td className="px-3 py-2">{memRaw} {memK ? `(${memK})` : ''}</td>
                            <td className="px-3 py-2">{stoRaw} {stoK ? `(${stoK})` : ''}</td>
                            <td className="px-3 py-2"><Chip status={livePhase} /></td>
                            <td className="px-3 py-2 text-right"><Button variant="secondary" onClick={() => onDeleteDeployment(s.name)}>Delete</Button></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* <footer className="mx-auto max-w-5xl px-4 pb-8 text-xs text-blue-400 text-center"></footer> */}
    </div>
  );
}

// text-emerald-300     //green 
//  'text-amber-300'    // Yellow for pending
//  'text-rose-300'     // Red for failure

