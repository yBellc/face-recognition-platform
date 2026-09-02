import { useEffect, useState } from "react";
import { getDashboard, DashboardData } from "../api";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, CartesianGrid, Legend,
} from "recharts";

function fmtMs(x: number | null | undefined) {
  if (x == null || !isFinite(x)) return "—";
  if (x < 1000) return `${x} ms`;
  return `${(x / 1000).toFixed(2)} s`;
}
function statusChip(s: string) {
  const cls =
    s === "processed" ? "bg-emerald-100 text-emerald-700" :
    s === "pending" ? "bg-amber-100 text-amber-700" :
    s === "failed" ? "bg-rose-100 text-rose-700" :
    "bg-slate-100 text-slate-600";
  return <span className={`chip ${cls}`}>{s}</span>;
}

// 后端不可用时只展示空状态，不伪造业务数据。
function makeUnavailable(): DashboardData {
  return {
    probe_image_count_today: 0,
    face_detected_count_today: 0,
    candidate_pending_review: 0,
    avg_processing_ms_today: 0,
    model_version: { tag: "—", decision_band: "—" },
    thresholds: { high: 0, medium: 0, low: 0 },
    band_counts: { high: 0, medium: 0, low: 0, rejected: 0 },
    project_summary: [],
    recent_probes: [],
  };
}

export default function DashboardPage() {
  const [d, setD] = useState<DashboardData | null>(null);
  const [usedMock, setUsedMock] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    let alive = true;
    const refresh = () => getDashboard()
      .then((data) => { if (alive) { setD(data); setUsedMock(false); setErr(null); setLastUpdated(new Date()); } })
      .catch((e) => {
        if (!alive) return;
        setErr(String(e.message || e));
        setD(makeUnavailable());
        setUsedMock(true);
      });
    refresh();
    const timer = window.setInterval(refresh, 10_000);
    window.addEventListener("focus", refresh);
    return () => { alive = false; window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, []);

  if (!d) return <div className="card card-body">加载中…</div>;

  // 防御性默认值，避免后端返回不完整对象时崩溃
  const th = d.thresholds ?? { high: 0.75, medium: 0.6, low: 0.45 };
  const bc = d.band_counts ?? { high: 0, medium: 0, low: 0, rejected: 0 };
  const rp = d.recent_probes ?? [];
  const mv = d.model_version ?? { tag: "unknown", decision_band: "high" };
  const ps = d.project_summary ?? [];

  const bandChart = [
    { name: "High (≥" + th.high + ")", value: bc.high, cls: "#10b981" },
    { name: "Medium", value: bc.medium, cls: "#f59e0b" },
    { name: "Low", value: bc.low, cls: "#0ea5e9" },
    { name: "Rejected", value: bc.rejected, cls: "#cbd5e1" },
  ];
  // 用最近 7 个探针的延迟构造一个时间线
  const latencyLine = [...rp].reverse().map((p, i) => ({
    name: `-${i + 1}m`,
    ms: p.processing_ms ?? 0,
    cands: p.candidate_count,
  }));

  const STAT = [
    { label: "今日探针图片", value: d.probe_image_count_today, icon: "📸", hint: "已上传待比对" },
    { label: "今日检测人脸数", value: d.face_detected_count_today, icon: "👤", hint: "每图可能多张" },
    { label: "待人工复核", value: d.candidate_pending_review, icon: "⏳", hint: "pending 候选条目", danger: d.candidate_pending_review > 30 },
    { label: "平均处理耗时", value: fmtMs(d.avg_processing_ms_today), icon: "⚡", hint: "端到端，p95 见评测" },
  ];

  return (
    <div className="dashboard-wallboard space-y-6">
      {usedMock && (
        <div className="card border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          ⚠ 后端 API 未连接（{err}），当前不展示业务统计。后端恢复后系统会自动同步真实数据。
        </div>
      )}

      {/* 四个统计卡片 */}
      <div className="mb-[-0.75rem] flex justify-end text-[11px] text-slate-400">{lastUpdated ? `自动更新于 ${lastUpdated.toLocaleTimeString()}` : "正在同步…"}</div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {STAT.map((s) => (
          <div key={s.label} className="card card-body">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs font-medium text-slate-500">{s.label}</div>
                <div className={"stat-value mt-2 " + (s.danger ? "text-rose-600" : "")}>{s.value}</div>
                <div className="text-[11px] text-slate-400 mt-1">{s.hint}</div>
              </div>
              <div className="text-2xl">{s.icon}</div>
            </div>
          </div>
        ))}
      </div>

      {/* 模型 + 阈值 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card">
          <div className="card-header"><span className="card-title">模型信息</span></div>
          <div className="card-body space-y-2">
            <div className="flex justify-between">
              <span className="label">模型版本</span>
              <span className="text-sm font-medium">{mv.tag}</span>
            </div>
            <div>
              <div className="label mb-1">阈值设置 (高/中/低)</div>
              <div className="relative h-6 rounded-md bg-slate-100 overflow-hidden">
                <div className="absolute inset-y-0 left-0" style={{ width: `${th.low * 100}%`, background: "#e2e8f0" }} />
                <div className="absolute inset-y-0" style={{ left: `${th.low * 100}%`, width: `${(th.medium - th.low) * 100}%`, background: "#bae6fd" }} />
                <div className="absolute inset-y-0" style={{ left: `${th.medium * 100}%`, width: `${(th.high - th.medium) * 100}%`, background: "#fde68a" }} />
                <div className="absolute inset-y-0" style={{ left: `${th.high * 100}%`, right: 0, background: "#a7f3d0" }} />
              </div>
              <div className="mt-2 grid grid-cols-3 text-xs text-slate-500">
                <span>Low ≥ {th.low}</span>
                <span className="text-center">Medium ≥ {th.medium}</span>
                <span className="text-right">High ≥ {th.high}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="card lg:col-span-1">
          <div className="card-header"><span className="card-title">决策带分布 (今日)</span></div>
          <div className="card-body h-56">
            <ResponsiveContainer>
              <BarChart data={bandChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" radius={[6, 6, 0, 0]} fill="#3b6cf6" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card lg:col-span-1">
          <div className="card-header"><span className="card-title">最近延迟趋势</span></div>
          <div className="card-body h-56">
            <ResponsiveContainer>
              <LineChart data={latencyLine}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="ms" name="耗时(ms)" stroke="#3b6cf6" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="cands" name="候选数" stroke="#f59e0b" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* 项目概览 + 最近探针 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card lg:col-span-1">
          <div className="card-header"><span className="card-title">项目概览</span></div>
          <div className="card-body">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-xs">
                  <th className="text-left pb-2">项目</th>
                  <th className="text-right pb-2">人员</th>
                  <th className="text-right pb-2">参考</th>
                  <th className="text-right pb-2">今日探针</th>
                </tr>
              </thead>
              <tbody>
                {ps.map(p => (
                  <tr key={p.project_id} className="border-t border-slate-100">
                    <td className="py-2 truncate max-w-[120px]" title={p.project_name}>{p.project_name}</td>
                    <td className="text-right">{p.subjects}</td>
                    <td className="text-right">{p.references}</td>
                    <td className="text-right font-medium">{p.probes_today}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card lg:col-span-2">
          <div className="card-header"><span className="card-title">最近探针活动</span></div>
          <div className="card-body">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-xs">
                  <th className="text-left pb-2">ID</th>
                  <th className="text-left pb-2">项目</th>
                  <th className="text-left pb-2">创建时间</th>
                  <th className="text-left pb-2">状态</th>
                  <th className="text-right pb-2">耗时</th>
                  <th className="text-right pb-2">候选数</th>
                </tr>
              </thead>
              <tbody>
                {rp.map(p => (
                  <tr key={p.id} className="border-t border-slate-100">
                    <td className="py-2 font-mono text-xs">#{p.id}</td>
                    <td>#{p.project_id}</td>
                    <td className="text-xs text-slate-500">{new Date(p.created_at).toLocaleString()}</td>
                    <td>{statusChip(p.processing_status)}</td>
                    <td className="text-right">{fmtMs(p.processing_ms)}</td>
                    <td className="text-right font-medium">{p.candidate_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
