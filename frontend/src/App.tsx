import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState, type FormEvent } from "react";
import api, { getCurrentUser, getPreferredProjectId, listProjects, login, logout, AuthUser, notifyProjectChange, projectLabel, Project } from "./api";

type NavItem = { to: string; label: string; icon: string; desc: string };

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "工作台", icon: "⌂", desc: "总览与快捷入口" },
  { to: "/dashboard", label: "态势总览", icon: "◒", desc: "项目状态与运行概览" },
  { to: "/persons", label: "对象库管理", icon: "◉", desc: "人员与参考照片" },
  { to: "/recognize", label: "现场图片识别", icon: "◎", desc: "上传并自动比对" },
  { to: "/review", label: "识别结果与复核", icon: "✓", desc: "逐人确认结果" },
  { to: "/datasets", label: "数据与实验", icon: "▦", desc: "项目与公开数据" },
  { to: "/evaluation", label: "评测报告", icon: "⌁", desc: "准确率与阈值" },
  { to: "/governance", label: "系统治理", icon: "◇", desc: "权限与部署准备" },
];

const WORKFLOW_STEPS = [
  { to: "/persons", label: "1 录入对象" },
  { to: "/recognize", label: "2 上传现场图片" },
  { to: "/review", label: "3 查看并复核" },
];

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [health, setHealth] = useState<{ healthy: boolean; latency: number; details: any } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [loginForm, setLoginForm] = useState({ username: "admin", password: "" });
  const [loginError, setLoginError] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [applyOpen, setApplyOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [availableProjects, setAvailableProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState(getPreferredProjectId(1));

  useEffect(() => {
    if (!localStorage.getItem("face_recog_token")) { setAuthReady(true); return; }
    getCurrentUser().then(setUser).catch(() => { logout(); }).finally(() => setAuthReady(true));
  }, []);

  useEffect(() => {
    if (!user) return;
    listProjects().then((items) => {
      setAvailableProjects(items || []);
      const preferred = getPreferredProjectId(items?.[0]?.id ?? 1);
      setActiveProjectId(items?.some((item) => item.id === preferred) ? preferred : (items?.[0]?.id ?? preferred));
    }).catch(() => {});
  }, [user]);

  useEffect(() => {
    const onProjectChange = (event: Event) => {
      const id = Number((event as CustomEvent).detail);
      if (Number.isFinite(id) && id > 0) setActiveProjectId(id);
    };
    window.addEventListener("face-project-change", onProjectChange);
    return () => window.removeEventListener("face-project-change", onProjectChange);
  }, []);

  useEffect(() => {
    let alive = true;
    api
      .get("/health")
      .then((r) => { if (alive) setHealth(r.data); })
      .catch((e) => { if (alive) setErr(String(e.message || e)); });
    return () => { alive = false; };
  }, [location.pathname]);

  useEffect(() => {
    const syncFullscreen = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch { /* 浏览器或嵌入容器不支持全屏时保持页面可用 */ }
  };

  const submitLogin = async (event: FormEvent) => {
    event.preventDefault();
    setLoggingIn(true); setLoginError("");
    try { setUser(await login(loginForm.username, loginForm.password)); }
    catch (e: any) { setLoginError(e.response?.data?.detail || "登录失败，请检查用户名和密码"); }
    finally { setLoggingIn(false); }
  };

  if (!authReady) return <div className="flex h-full items-center justify-center bg-slate-950 text-slate-300">正在验证访问权限…</div>;
  if (!user) return (
    <div className="login-screen flex min-h-full items-center justify-center p-5 lg:p-10">
      <div className="login-shell grid w-full max-w-5xl overflow-hidden rounded-[28px] border border-white/10 bg-slate-950/70 text-white shadow-2xl shadow-slate-950/40 backdrop-blur-xl lg:grid-cols-[1.05fr_.95fr]">
        <div className="login-story relative hidden overflow-hidden p-10 lg:flex lg:flex-col lg:justify-between">
          <div className="login-orbit login-orbit-one" /><div className="login-orbit login-orbit-two" />
          <div className="relative z-10"><div className="flex items-center gap-3"><div className="brand-mark">F</div><div><div className="font-semibold tracking-wide">重点对象识别平台</div><div className="text-xs text-cyan-100/60">安全登录 · 操作全程留痕</div></div></div>
            <div className="mt-20 max-w-md"><div className="eyebrow-dark">FIELD INTELLIGENCE / 01</div><h2 className="mt-4 text-4xl font-semibold leading-tight tracking-[-0.04em]">把每一次识别，<br /><span className="text-cyan-200">变成可复核的证据。</span></h2><p className="mt-5 text-sm leading-6 text-slate-300/75">从重点对象建档、现场图片比对，到人工复核与结果归档，一条路径完成闭环。</p></div>
          </div>
          <div className="relative z-10 grid grid-cols-3 gap-3 text-xs text-slate-300/70"><div className="login-metric"><span>01</span><b>对象库</b><small>参考照片与特征</small></div><div className="login-metric"><span>02</span><b>多脸识别</b><small>逐人对应候选</small></div><div className="login-metric"><span>03</span><b>人工复核</b><small>结论留痕可导出</small></div></div>
        </div>
        <form onSubmit={submitLogin} className="login-form p-7 sm:p-10">
          <div className="mb-9 flex items-center gap-3 lg:hidden"><div className="brand-mark">F</div><div><div className="font-semibold">重点对象识别平台</div><div className="text-xs text-indigo-200/70">安全登录 · 操作全程留痕</div></div></div>
          <div className="mb-6"><div className="eyebrow-dark">WELCOME BACK</div><div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">欢迎回来</div><div className="mt-2 text-sm text-slate-300/70">登录后才能访问对象库和识别结果</div></div>
        <label className="mb-3 block text-xs text-indigo-100/80">账号<input className="mt-1 w-full rounded-lg border border-white/15 bg-white/10 px-3 py-2.5 text-sm text-white outline-none focus:ring-2 focus:ring-cyan-300/50" value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} /></label>
        <label className="mb-4 block text-xs text-indigo-100/80">密码<input type="password" className="mt-1 w-full rounded-lg border border-white/15 bg-white/10 px-3 py-2.5 text-sm text-white outline-none focus:ring-2 focus:ring-cyan-300/50" value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} /></label>
        {loginError && <div className="mb-3 rounded-lg border border-rose-300/20 bg-rose-500/15 px-3 py-2 text-xs text-rose-200">⚠ {loginError}</div>}
        <button disabled={loggingIn} className="login-submit w-full rounded-xl px-4 py-3 text-sm font-semibold text-slate-950 transition">{loggingIn ? "验证中…" : "登录平台"}<span aria-hidden="true">↗</span></button>
        <div className="mt-4 flex items-center justify-between text-[11px] text-slate-400"><span>本地开发账号由部署环境变量配置</span><button type="button" className="text-cyan-200 hover:text-white" onClick={() => setApplyOpen((v) => !v)}>{applyOpen ? "收起" : "申请访问"}</button></div>
        {applyOpen && <div className="mt-4 rounded-xl border border-cyan-200/15 bg-cyan-300/8 p-3 text-xs leading-5 text-slate-300"><div className="font-medium text-cyan-100">敏感数据平台不开放自助注册</div><div className="mt-1">请联系管理员在“系统治理 → 账号与项目授权”中创建账号，并分配可访问项目。这样每次授权、变更和撤回都能留下审计记录。</div></div>}
        <div className="mt-3 text-[11px] text-slate-500">正式部署请通过环境变量修改演示账号，并启用 HTTPS。</div>
      </form>
      </div>
    </div>
  );

  const currentTitle = NAV_ITEMS.find(n => n.to === location.pathname)?.label ?? "工作台";

  return (
    <div className="app-shell flex h-full bg-slate-50">
      {/* 侧边栏 */}
      <aside className="app-sidebar w-64 shrink-0 text-white flex flex-col">
        <div className="sidebar-brand h-[76px] flex items-center px-5">
          <div className="brand-mark relative">F</div>
          <div className="ml-3">
            <div className="font-semibold text-sm leading-tight tracking-wide">重点对象识别平台</div>
            <div className="text-[11px] text-indigo-200/70 mt-0.5">图片识别 · 人工复核</div>
          </div>
        </div>

        <div className="sidebar-context mx-4 mt-4 rounded-xl px-3 py-2.5"><div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">当前项目</div><div className="mt-1 flex items-center justify-between text-xs"><span className="truncate">{projectLabel(availableProjects.find((item) => item.id === activeProjectId) || { id: activeProjectId, name: `项目 #${activeProjectId}` })}</span><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /></div></div>
        <nav className="flex-1 p-4 space-y-1.5">
          <div className="px-3 pb-2 text-[10px] uppercase tracking-[0.2em] text-indigo-200/50">日常工作</div>
          {NAV_ITEMS.slice(0, 5).map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                "group flex items-center gap-3 px-3 py-3 rounded-xl text-sm transition-all duration-200 " +
                (isActive
                  ? "bg-white/12 text-white font-medium shadow-lg shadow-black/10 ring-1 ring-white/10"
                  : "text-indigo-100/70 hover:bg-white/8 hover:text-white")
              }
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/8 text-base font-semibold group-hover:bg-cyan-300/20">{n.icon}</span>
              <span className="min-w-0"><span className="block truncate">{n.label}</span><span className="block text-[10px] text-indigo-200/45 mt-0.5">{n.desc}</span></span>
            </NavLink>
          ))}
          <div className="px-3 pt-5 pb-2 text-[10px] uppercase tracking-[0.2em] text-indigo-200/50">数据与审计</div>
          {NAV_ITEMS.slice(5).map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `group flex items-center gap-3 px-3 py-3 rounded-xl text-sm transition-all duration-200 ${isActive ? "bg-white/12 text-white font-medium shadow-lg shadow-black/10 ring-1 ring-white/10" : "text-indigo-100/70 hover:bg-white/8 hover:text-white"}`}>
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/8 text-base font-semibold group-hover:bg-cyan-300/20">{n.icon}</span>
              <span className="min-w-0"><span className="block truncate">{n.label}</span><span className="block text-[10px] text-indigo-200/45 mt-0.5">{n.desc}</span></span>
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-white/10 text-[11px] text-indigo-100/60 space-y-2">
          <div className="flex items-center gap-2 rounded-lg bg-white/6 px-3 py-2">
            <span className={`w-2 h-2 rounded-full ${health ? (health.healthy ? "bg-emerald-500" : "bg-rose-500") : "bg-amber-400"} animate-pulse`} />
            <span>后端: {health ? (health.healthy ? "已连接" : "异常") : "未连接"}</span>
          </div>
          {err && <div className="text-rose-300">⚠ API 未启动</div>}
          <div className="leading-relaxed text-indigo-200/45">
            系统输出候选，最终结论由人工复核
          </div>
        </div>
      </aside>

      {/* 主区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 顶栏 */}
        <header className="app-header h-[76px] shrink-0 px-7 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div><div className="text-[10px] uppercase tracking-[0.2em] text-slate-400">工作台 <span className="mx-1 text-slate-300">/</span> 当前页面</div><div className="flex items-end gap-3"><h1 className="text-xl font-semibold text-slate-900 mt-1">{currentTitle}</h1><span className="hidden pb-0.5 text-xs text-slate-400 md:block">{NAV_ITEMS.find(n => n.label === currentTitle)?.desc}</span></div></div>
          </div>
          <div className="flex items-center gap-4 text-xs text-slate-500">
            {availableProjects.length > 0 && <label className="hidden items-center gap-2 lg:flex"><span className="text-slate-400">项目</span><select aria-label="切换当前项目" className="project-switcher rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm" value={activeProjectId} onChange={(e) => notifyProjectChange(Number(e.target.value))}>{availableProjects.map((p) => <option key={p.id} value={p.id}>{projectLabel(p)}（#{p.id}）</option>)}</select></label>}
            <button className="hidden items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500 shadow-sm transition hover:border-indigo-200 hover:text-indigo-600 lg:flex" onClick={() => navigate('/recognize')}><span className="text-base leading-none">＋</span>新建识别任务</button>
            <button title="仅切换浏览器全屏，当前布局已默认适配宽屏" className="hidden items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500 shadow-sm transition hover:border-slate-300 hover:text-slate-800 xl:flex" onClick={toggleFullscreen}><span className="text-sm leading-none">{isFullscreen ? "⤢" : "⛶"}</span>{isFullscreen ? "退出全屏" : "全屏展示"}</button>
            {health?.details?.model_version && (
                <span className="hidden md:flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />识别引擎 <strong className="text-slate-700">{health.details.model_version.tag}</strong>
              </span>
            )}
            <div className="relative flex items-center gap-2"><div className="hidden sm:block text-right"><div className="text-xs font-medium text-slate-700">{user.username}</div><div className="text-[10px] text-slate-400">{user.role === "admin" ? "管理员" : user.role === "operator" ? "操作员" : "复核员"}</div></div><button title="打开用户菜单" aria-expanded={profileOpen} onClick={() => setProfileOpen((v) => !v)} className="profile-trigger w-9 h-9 rounded-full bg-gradient-to-br from-indigo-100 to-cyan-100 flex items-center justify-center text-indigo-700 ring-4 ring-indigo-50">👤</button>{profileOpen && <div className="profile-menu absolute right-0 top-12 z-50 w-56 rounded-xl border border-slate-200 bg-white p-2 shadow-xl"><div className="border-b border-slate-100 px-3 py-2"><div className="text-sm font-semibold text-slate-800">{user.username}</div><div className="mt-0.5 text-xs text-slate-400">{user.role === "admin" ? "管理员" : user.role === "operator" ? "操作员" : "复核员"}</div></div><button className="mt-1 flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs text-slate-600 transition hover:bg-slate-50" onClick={() => { setProfileOpen(false); navigate('/governance'); }}>账号与权限 <span>→</span></button><button className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs text-rose-600 transition hover:bg-rose-50" onClick={() => { logout(); setUser(null); setProfileOpen(false); }}>退出登录 <span>↗</span></button></div>}</div>
          </div>
        </header>

        <main className="app-main flex-1 overflow-auto p-6">
          {WORKFLOW_STEPS.some((step) => location.pathname === step.to) && (
            <div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl border border-indigo-100 bg-white/90 px-4 py-3 shadow-sm backdrop-blur">
              <span className="mr-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">工作流程</span>
              {WORKFLOW_STEPS.map((step, index) => {
                const active = location.pathname === step.to;
                const complete = WORKFLOW_STEPS.findIndex((item) => item.to === location.pathname) > index;
                return (
                  <div key={step.to} className="flex items-center gap-2">
                    <NavLink
                      to={step.to}
                      className={`rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
                        active ? "bg-indigo-600 text-white shadow-md shadow-indigo-200" : complete ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500 hover:bg-indigo-50 hover:text-indigo-600"
                      }`}
                    >
                      {complete ? "✓ " : ""}{step.label}
                    </NavLink>
                    {index < WORKFLOW_STEPS.length - 1 && <span className="text-slate-300">›</span>}
                  </div>
                );
              })}
              <span className="ml-auto text-xs text-slate-400">识别结果仅供人工复核</span>
            </div>
          )}
          <div key={location.pathname} className="route-surface"><Outlet /></div>
        </main>
      </div>
    </div>
  );
}
