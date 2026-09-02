import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboard, DashboardData } from "../api";

export default function HomePage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    let alive = true;
    const refresh = () => getDashboard()
      .then((next) => { if (alive) { setData(next); setError(""); setLastUpdated(new Date()); } })
      .catch((e) => { if (alive) setError(e?.message || "后端暂不可用"); });
    refresh();
    const timer = window.setInterval(refresh, 10_000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      alive = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);

  const steps = [
    { n: "1", title: "导入重点关注对象", desc: "录入人员编号，上传 1 张或多张参考照片，也可按文件夹批量导入", to: "/persons", action: "进入人员库" },
    { n: "2", title: "上传每天拍摄的照片", desc: "一张图片可以检测并比对多张人脸", to: "/recognize", action: "上传照片" },
    { n: "3", title: "查看结果并复核", desc: "逐张查看候选、相似度和未匹配人脸", to: "/review", action: "查看结果" },
  ];

  return (
    <div className="space-y-6">
      <div className="home-hero relative overflow-hidden rounded-2xl p-7 text-white shadow-xl">
        <div className="home-hero-grid pointer-events-none absolute inset-0" />
        <div className="relative flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-slate-300"><span className="h-2 w-2 rounded-full bg-emerald-400" /> Operations / Today</div>
            <h2 className="text-3xl font-semibold tracking-tight">重点对象识别工作台</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300/85">从对象建档、现场图片比对到人工复核，所有任务在一个清晰的工作区完成。</p>
          </div>
          <div className="flex items-center gap-5">
            <div className="home-hero-visual" aria-hidden="true">
              <div className="face-frame"><i className="face-corner face-corner-tl" /><i className="face-corner face-corner-tr" /><i className="face-corner face-corner-bl" /><i className="face-corner face-corner-br" /><div className="face-outline"><span className="face-eye face-eye-left" /><span className="face-eye face-eye-right" /><span className="face-nose" /><span className="face-mouth" /></div><div className="face-scan-line" /></div>
              <div className="face-meta"><span className="face-dot" /> FACE MATCH / READY</div>
            </div>
            <div className="home-hero-kpi rounded-xl px-4 py-3 text-right"><div className="text-[10px] uppercase tracking-widest text-slate-300/70">今日处理</div><div className="mt-1 text-2xl font-semibold">{data?.probe_image_count_today ?? "—"}</div><div className="text-[11px] text-slate-400">张现场图片</div></div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {steps.map((step) => (
          <div key={step.n} className="card motion-card p-5 flex flex-col group hover:-translate-y-1">
            <div className="flex items-center justify-between"><div className="flex h-10 w-10 rounded-xl bg-gradient-to-br from-indigo-500 to-cyan-400 text-white items-center justify-center font-semibold shadow-lg shadow-indigo-200">{step.n}</div><span className="text-xs uppercase tracking-widest text-slate-300">STEP {step.n}</span></div>
            <h3 className="font-semibold text-slate-800 mt-4">{step.title}</h3>
            <p className="text-sm text-slate-500 mt-2 flex-1">{step.desc}</p>
            <Link to={step.to} className="btn-primary mt-4 w-full justify-center">{step.action} <span className="transition-transform group-hover:translate-x-1">→</span></Link>
          </div>
        ))}
      </div>

      <div className="card motion-card p-5">
        <div className="flex items-center justify-between mb-4"><div><div className="text-[10px] uppercase tracking-[0.18em] text-slate-400">Live status</div><h3 className="font-semibold text-slate-800 mt-1">当前系统状态</h3></div><div className="flex items-center gap-4"><span className="text-[11px] text-slate-400">{lastUpdated ? `自动更新于 ${lastUpdated.toLocaleTimeString()}` : "正在同步…"}</span><Link to="/evaluation" className="text-xs text-indigo-600 hover:underline">查看实验评测 →</Link></div></div>
        {error ? <div className="text-sm text-rose-600">后端暂不可用：{error}</div> : <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="motion-card rounded-xl bg-slate-50 p-3 ring-1 ring-slate-100"><div className="text-xs text-slate-500">今日上传图片</div><div className="text-xl font-semibold text-slate-800 mt-1">{data?.probe_image_count_today ?? "—"}</div></div>
          <div className="motion-card rounded-xl bg-slate-50 p-3 ring-1 ring-slate-100"><div className="text-xs text-slate-500">今日检测人脸</div><div className="text-xl font-semibold text-slate-800 mt-1">{data?.face_detected_count_today ?? "—"}</div></div>
          <div className="motion-card rounded-xl bg-amber-50 p-3 ring-1 ring-amber-100"><div className="text-xs text-amber-700">待复核候选</div><div className="text-xl font-semibold text-amber-600 mt-1">{data?.candidate_pending_review ?? "—"}</div></div>
          <div className="motion-card rounded-xl bg-slate-50 p-3 ring-1 ring-slate-100"><div className="text-xs text-slate-500">识别引擎</div><div className="text-sm font-semibold text-slate-800 mt-2 truncate">{data?.model_version?.tag ?? "—"}</div></div>
        </div>}
      </div>
    </div>
  );
}
