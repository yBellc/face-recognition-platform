import { useEffect, useState } from "react";
import api, { exportCandidateResults, getPreferredProjectId, listProjects, notifyProjectChange, projectLabel, Project } from "../api";

type Thresholds = { project_id: number; high: number; medium: number; low: number; source: string; sample_count: number; calibrated_at?: string | null; notes?: string };
type Monitoring = { total: number; processed: number; failed: number; queued: number; latency_p50_ms?: number | null; latency_p95_ms?: number | null; model_version: string };

export default function GovernancePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(getPreferredProjectId(1));
  const [thresholds, setThresholds] = useState<Thresholds | null>(null);
  const [policy, setPolicy] = useState<{ retention_days: number; data_policy: string } | null>(null);
  const [monitoring, setMonitoring] = useState<Monitoring | null>(null);
  const [consentRef, setConsentRef] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [consents, setConsents] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const [newUser, setNewUser] = useState({ username: "", password: "", role: "reviewer", project_ids: "" });
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [exportScope, setExportScope] = useState<"project" | "all">("project");

  const load = async (id: number) => {
    try {
      const [t, c, p] = await Promise.all([
        api.get(`/api/v1/projects/${id}/thresholds`),
        api.get(`/api/v1/projects/${id}/consents`),
        api.get(`/api/v1/projects/${id}/policy`),
      ]);
      setThresholds(t.data); setConsents(c.data || []); setPolicy(p.data);
    } catch (e: any) { setMessage(e.response?.data?.detail || "治理配置读取失败"); }
  };

  useEffect(() => {
    listProjects().then((items) => {
      setProjects(items);
      const preferred = getPreferredProjectId(items[0]?.id ?? 1);
      const next = items.find((item) => item.id === preferred)?.id ?? items[0]?.id ?? preferred;
      setProjectId(next);
      notifyProjectChange(next);
      if (next) load(next);
    }).catch(() => {});
    api.get("/api/v1/monitoring/summary").then((r) => setMonitoring(r.data)).catch(() => {});
    api.get("/api/v1/admin/users").then((r) => setUsers(r.data || [])).catch(() => {});
  }, []);

  useEffect(() => {
    const onProjectChange = (event: Event) => {
      const id = Number((event as CustomEvent).detail);
      if (!Number.isFinite(id) || id <= 0 || id === projectId) return;
      setProjectId(id);
      load(id);
    };
    window.addEventListener("face-project-change", onProjectChange);
    return () => window.removeEventListener("face-project-change", onProjectChange);
  }, [projectId]);

  const createUser = async () => {
    try {
      const project_ids = newUser.project_ids.split(",").map((v) => Number(v.trim())).filter((v) => Number.isFinite(v) && v > 0);
      const r = await api.post("/api/v1/admin/users", { ...newUser, project_ids });
      setUsers((items) => [...items, r.data]); setNewUser({ username: "", password: "", role: "reviewer", project_ids: "" }); setMessage("账号已创建并完成项目授权");
    } catch (e: any) { setMessage(e.response?.data?.detail || "账号创建失败"); }
  };

  const saveThresholds = async () => {
    if (!thresholds) return;
    setSaving(true); setMessage("");
    try { const r = await api.put(`/api/v1/projects/${projectId}/thresholds`, thresholds); setThresholds(r.data); setMessage("阈值已保存；后续识别将使用该项目阈值"); }
    catch (e: any) { setMessage(e.response?.data?.detail || "阈值保存失败"); }
    finally { setSaving(false); }
  };

  const createConsent = async () => {
    if (!consentRef.trim()) return;
    try { await api.post(`/api/v1/projects/${projectId}/consents`, { consent_ref: consentRef.trim(), expires_at: expiresAt || undefined }); setConsentRef(""); setExpiresAt(""); await load(projectId); setMessage("授权记录已登记"); }
    catch (e: any) { setMessage(e.response?.data?.detail || "授权记录保存失败"); }
  };

  const savePolicy = async () => {
    if (!policy) return;
    try { const r = await api.put(`/api/v1/projects/${projectId}/policy`, policy); setPolicy(r.data); setMessage("保留期限与删除策略已保存"); }
    catch (e: any) { setMessage(e.response?.data?.detail || "策略保存失败"); }
  };

  const exportResults = async () => {
    try { await exportCandidateResults(exportScope === "project" ? { projectId } : {}); setMessage(exportScope === "project" ? "当前项目结果已导出" : "全部项目结果已导出"); }
    catch (e: any) { setMessage(e.response?.data?.detail || "结果导出失败"); }
  };

  return (
    <div className="space-y-6 pb-8">
      <div className="rounded-xl border border-indigo-100 bg-indigo-50/70 px-4 py-3 text-xs leading-5 text-indigo-900"><span className="font-semibold">导出怎么理解：</span>治理页导出一个项目或全部项目；复核页导出单张图片。文件按人脸结果逐行记录，包含无候选的人脸，便于领导核对“检测到但无法判断”的情况。</div>
      <div className="relative overflow-hidden rounded-2xl border border-indigo-900/60 bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 p-7 text-white shadow-xl shadow-indigo-950/10">
        <div className="pointer-events-none absolute -right-16 -top-20 h-64 w-64 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="relative flex flex-wrap items-end justify-between gap-4"><div><div className="text-xs uppercase tracking-[0.2em] text-indigo-200">Governance center</div><h2 className="mt-2 text-2xl font-semibold">系统治理与部署准备</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">统一管理账号权限、授权凭证、阈值校准、运行健康和结果导出。这里的配置都会写入审计记录。</p></div><select className="rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm text-white" value={projectId} onChange={(e) => { const id = Number(e.target.value); setProjectId(id); notifyProjectChange(id); load(id); }}>{projects.map((p) => <option className="text-slate-800" key={p.id} value={p.id}>{projectLabel(p)}（#{p.id}）</option>)}</select></div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {[['处理总量', monitoring?.total ?? '—'], ['已完成', monitoring?.processed ?? '—'], ['失败', monitoring?.failed ?? '—'], ['队列中', monitoring?.queued ?? '—'], ['p95耗时', monitoring?.latency_p95_ms ? `${monitoring.latency_p95_ms}ms` : '—']].map(([label, value]) => <div key={label} className="card p-4"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 text-xl font-semibold text-slate-900">{value}</div></div>)}
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <section className="card p-5 xl:col-span-2"><div className="flex items-start justify-between"><div><div className="text-[10px] uppercase tracking-[0.18em] text-indigo-500">P0 · Calibration</div><h3 className="mt-1 text-base font-semibold text-slate-900">阈值校准</h3><p className="mt-1 text-xs text-slate-500">当前值仅作为演示默认值；使用授权验证集后填写校准结果。</p></div><span className={`chip ${thresholds?.source === 'default_demo' ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}`}>{thresholds?.source === 'default_demo' ? '待校准' : '已校准'}</span></div>
          {thresholds && <div className="mt-5 grid grid-cols-3 gap-3">{(['low','medium','high'] as const).map((key) => <label key={key} className="text-xs text-slate-500">{key === 'low' ? '最低阈值' : key === 'medium' ? '中置信阈值' : '高置信阈值'}<input type="number" min="0.01" max="0.99" step="0.01" className="input mt-1" value={thresholds[key]} onChange={(e) => setThresholds({ ...thresholds, [key]: Number(e.target.value), source: 'manual_calibration' })} /></label>)}</div>}
          <div className="mt-4 flex items-center gap-3"><input className="input max-w-[180px]" placeholder="验证样本数" value={thresholds?.sample_count ?? 0} onChange={(e) => thresholds && setThresholds({ ...thresholds, sample_count: Number(e.target.value) })} /><button className="btn-primary" disabled={!thresholds || saving} onClick={saveThresholds}>{saving ? '保存中…' : '保存校准阈值'}</button></div>
        </section>

        <section className="card p-5"><div className="text-[10px] uppercase tracking-[0.18em] text-indigo-500">P0 · Privacy</div><h3 className="mt-1 text-base font-semibold text-slate-900">授权与数据保留</h3><p className="mt-1 text-xs text-slate-500">先登记授权凭证，再按项目策略自动清理到期数据。</p><input className="input mt-4" placeholder="授权凭证编号 / 文件编号" value={consentRef} onChange={(e) => setConsentRef(e.target.value)} /><input type="date" className="input mt-2" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} /><button className="btn-primary mt-3 w-full justify-center" disabled={!consentRef.trim()} onClick={createConsent}>登记授权记录</button><div className="mt-4 border-t border-slate-100 pt-3"><label className="text-xs text-slate-500">数据保留期限（天）<input className="input mt-1" type="number" min="1" max="3650" value={policy?.retention_days ?? 365} onChange={(e) => policy && setPolicy({ ...policy, retention_days: Number(e.target.value) })} /></label><textarea className="input mt-2 min-h-16" placeholder="删除策略说明（到期删除、撤回授权即删除等）" value={policy?.data_policy ?? ""} onChange={(e) => policy && setPolicy({ ...policy, data_policy: e.target.value })} /><button className="btn-secondary mt-2 w-full justify-center" onClick={savePolicy}>保存数据策略</button></div><div className="mt-4 space-y-2">{consents.slice(0, 4).map((c) => <div key={c.id} className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><div className="font-medium text-slate-700">{c.consent_ref}</div><div className="mt-0.5 text-slate-400">状态：{c.status} {c.expires_at ? `· 到期 ${c.expires_at.slice(0,10)}` : ''}</div></div>)}{!consents.length && <div className="text-xs text-slate-400">当前项目暂无授权记录</div>}</div></section>
      </div>

      <section className="card p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><div className="text-[10px] uppercase tracking-[0.18em] text-indigo-500">P1 · Evidence</div><h3 className="mt-1 text-base font-semibold text-slate-900">结果导出与运行监控</h3><p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">导出粒度为“候选行”：每一行包含图片编号、人脸编号、对象编号、相似度、时间、复核结论和模型版本。可导出当前项目或全部项目，单张图片可在复核页导出。</p></div><div className="flex items-center gap-2"><select className="input w-auto min-w-44" value={exportScope} onChange={(e) => setExportScope(e.target.value as "project" | "all")}><option value="project">当前项目全部图片</option><option value="all">全部项目汇总</option></select><button className="btn-primary" onClick={exportResults}>导出 CSV</button></div></div>{monitoring && <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-3"><div className="rounded-xl bg-emerald-50 p-4"><div className="text-xs text-emerald-700">成功率</div><div className="mt-1 text-xl font-semibold text-emerald-800">{monitoring.total ? `${((monitoring.processed / monitoring.total) * 100).toFixed(1)}%` : '—'}</div></div><div className="rounded-xl bg-rose-50 p-4"><div className="text-xs text-rose-700">失败数</div><div className="mt-1 text-xl font-semibold text-rose-800">{monitoring.failed}</div></div><div className="rounded-xl bg-indigo-50 p-4"><div className="text-xs text-indigo-700">当前模型版本</div><div className="mt-1 text-sm font-semibold text-indigo-900">{monitoring.model_version}</div></div></div>}</section>
      <section className="card p-5"><div className="flex items-start justify-between"><div><div className="text-[10px] uppercase tracking-[0.18em] text-indigo-500">P0 · Access control</div><h3 className="mt-1 text-base font-semibold text-slate-900">账号与项目授权</h3><p className="mt-1 text-xs text-slate-500">管理员创建账号并指定角色、可访问项目；普通账号只能看到授权项目。</p></div><span className="chip bg-emerald-100 text-emerald-700">{users.length} 个账号</span></div><div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-5"><input className="input" placeholder="账号" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} /><input className="input" type="password" placeholder="初始密码（至少8位）" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} /><select className="input" value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}><option value="reviewer">复核员</option><option value="operator">操作员</option><option value="admin">管理员</option></select><input className="input" placeholder="项目编号，如 1,2" value={newUser.project_ids} onChange={(e) => setNewUser({ ...newUser, project_ids: e.target.value })} /><button className="btn-primary" disabled={!newUser.username || newUser.password.length < 8} onClick={createUser}>创建账号</button></div><div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-3">{users.map((u) => <div key={u.id} className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><div className="font-medium text-slate-700">{u.username} <span className="ml-1 text-indigo-600">{u.role === 'admin' ? '管理员' : u.role === 'operator' ? '操作员' : '复核员'}</span></div><div className="mt-1 text-slate-400">授权项目：{u.project_ids?.length ? u.project_ids.join(', ') : '全部（管理员）'}</div></div>)}</div></section>
      {message && <div className="rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-3 text-sm text-indigo-800">{message}</div>}
    </div>
  );
}
