import { useEffect, useState } from "react";
import api from "../api";

interface EvalRun {
  id: number;
  name: string;
  dataset_name?: string;
  model_version?: string;
  protocol?: string;
  status: "running" | "success" | "failed";
  started_at: string;
  completed_at: string | null;
  metrics_json?: {
    AUC?: number;
    EER?: number;
    FNMR_at_FMR001?: number;
    latency_p50?: number;
    latency_p95?: number;
    latency_p99?: number;
    total_probes?: number;
    total_pairs?: number;
    total_images?: number;
    num_subjects?: number;
    protocol?: string;
    accuracy?: number;
    top1?: number;
    top5?: number;
    false_accepts?: number;
    false_rejects?: number;
    eer_threshold?: number;
    threshold_at_fmr_0_001?: number;
  };
  summary?: string;
}

interface Props {
  projectId: number;
}

export default function EvaluationPage({ projectId }: Props) {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvalRun | null>(null);
  const [dashboardData, setDashboardData] = useState<any>(null);

  const loadRuns = async () => {
    try {
      const r = await api.get("/api/v1/evaluation/runs");
      setRuns(r.data || []);
      if (r.data?.length > 0 && !selectedRun) {
        setSelectedRun(r.data[0]);
      }
    } catch {}
  };

  const loadDashboard = async () => {
    try {
      const r = await api.get("/api/v1/dashboard");
      setDashboardData(r.data);
    } catch {}
  };

  useEffect(() => { loadRuns(); loadDashboard(); }, [projectId]);

  const m = selectedRun?.metrics_json || {};

  const MetricCard = ({ label, value, suffix, color }: { label: string; value: number | string; suffix?: string; color: string }) => (
    <div className={`bg-white rounded-lg border border-slate-200 p-4`}>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>
        {typeof value === "number" ? value.toFixed(4) : value}
        {suffix && <span className="text-sm ml-1 text-slate-400">{suffix}</span>}
      </div>
    </div>
  );

  return (
    <div className="evaluation-page space-y-6">
      {/* 数据集 + 模型信息 */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-lg border border-slate-200 p-5">
          <div className="text-xs text-slate-500 mb-3">数据集信息</div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">数据集</span>
              <span className="font-medium text-slate-800">{selectedRun?.dataset_name || selectedRun?.name || "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">总图片数</span>
              <span className="font-medium text-slate-800">
                {m.total_images != null ? `${m.total_images} 张` : m.total_probes != null ? `${m.total_probes} 张 probe` : "—"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">人员数量</span>
              <span className="font-medium text-slate-800">{m.num_subjects != null ? `${m.num_subjects} 人` : "未记录"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">来源</span>
              <span className="font-medium text-slate-800">以评测记录中的来源为准</span>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-lg border border-slate-200 p-5">
          <div className="text-xs text-slate-500 mb-3">模型版本</div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">检测模型</span>
              <span className="font-medium text-slate-800">{selectedRun?.model_version || "以评测记录为准"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">识别模型</span>
              <span className="font-medium text-slate-800">ArcFace R50（buffalo_l）</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">特征维度</span>
              <span className="font-medium text-slate-800">512-D</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">运行环境</span>
              <span className="font-medium text-slate-800">CPU / ONNX Runtime</span>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-700">本次评测到底做了什么？</h3>
          {selectedRun && <span className="text-xs text-slate-400">实验记录 #{selectedRun.id}</span>}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
          {[
            ["1", "检测", "SCRFD 在图片中定位人脸并过滤不可用人脸"],
            ["2", "提取特征", "ArcFace 将每张脸转换为 512 维特征向量"],
            ["3", "计算相似度", "使用归一化向量余弦相似度进行一对一或一对多比较"],
            ["4", "判定阈值", `达到阈值才进入候选；当前记录阈值 ${m.threshold_at_fmr_0_001?.toFixed?.(4) ?? m.eer_threshold?.toFixed?.(4) ?? "以记录为准"}`],
          ].map(([n, title, desc]) => (
            <div key={n} className="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <div className="flex items-center gap-2 mb-1"><span className="w-5 h-5 rounded-full bg-indigo-600 text-white flex items-center justify-center font-medium">{n}</span><span className="font-medium text-slate-700">{title}</span></div>
              <div className="text-slate-500 leading-relaxed">{desc}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 text-xs text-slate-500">AUC 越接近 1 越好；EER 和 FNMR 越低越好。公开 LFW 结果只能作为通用照片基线，不能直接等同于真实车内监控准确率。</div>
      </div>

      {/* 核心指标 */}
      <div className="bg-white rounded-lg border border-slate-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-700">核心识别指标</h3>
          {selectedRun && (
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              selectedRun.status === "success" ? "bg-emerald-50 text-emerald-600" :
              selectedRun.status === "running" ? "bg-amber-50 text-amber-600" :
              "bg-rose-50 text-rose-600"
            }`}>
              {selectedRun.status === "success" ? "评测完成" : selectedRun.status === "running" ? "运行中" : "失败"}
            </span>
          )}
        </div>
        <div className="grid grid-cols-5 gap-3">
          <MetricCard label="AUC" value={m.AUC ?? "—"} color="text-emerald-600" />
          <MetricCard label="EER" value={m.EER ?? "—"} color="text-emerald-600" />
          <MetricCard label="FNMR@FMR=0.1%" value={m.FNMR_at_FMR001 ?? "—"} color="text-rose-600" />
          <MetricCard label="验证对数" value={m.total_pairs ?? "—"} color="text-indigo-600" />
          <MetricCard label="测试身份数" value={m.num_subjects ?? "—"} color="text-indigo-600" />
        </div>
        {selectedRun && (!m.num_subjects || m.num_subjects <= 4) && (
          <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
            当前评测身份数量较少，结果只能作为原型或流程验证，不能外推到大规模人员库或真实车内部署。
          </div>
        )}
        {typeof m.protocol === "string" && m.protocol && (
          <div className="mt-3 text-xs text-slate-500">评测协议：{m.protocol}</div>
        )}
        {(m.top1 !== undefined || m.top5 !== undefined) && (
          <div className="mt-3 text-xs text-slate-500">附加检索指标（不作为一对一验证主结论）：Top-1 {m.top1 != null ? `${(m.top1 * 100).toFixed(2)}%` : "—"}，Top-5 {m.top5 != null ? `${(m.top5 * 100).toFixed(2)}%` : "—"}。</div>
        )}
      </div>

      {/* 误报案例 */}
      <div className="bg-white rounded-lg border border-slate-200 p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-4">误报案例统计</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="p-4 bg-rose-50 rounded-lg">
            <div className="text-xs text-rose-600 mb-1">假阳性 (False Accepts)</div>
            <div className="text-3xl font-bold text-rose-700">{m.false_accepts ?? 0}</div>
            <div className="text-xs text-rose-500 mt-1">将不同人员误判为同一人</div>
          </div>
          <div className="p-4 bg-amber-50 rounded-lg">
            <div className="text-xs text-amber-600 mb-1">假阴性 (False Rejects)</div>
            <div className="text-3xl font-bold text-amber-700">{m.false_rejects ?? 0}</div>
            <div className="text-xs text-amber-500 mt-1">将同一人误判为不同人员</div>
          </div>
        </div>
        {selectedRun?.summary && (
          <div className="mt-4 p-3 bg-slate-50 rounded border border-slate-200 text-xs text-slate-600">
            <strong>说明：</strong> {selectedRun.summary}
          </div>
        )}
      </div>

      {/* 延迟统计 */}
      <div className="bg-white rounded-lg border border-slate-200 p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-4">延迟统计</h3>
        <div className="grid grid-cols-3 gap-3">
          <MetricCard label="平均延迟" value={
            m.latency_p50 ?? dashboardData?.avg_processing_ms_today ?? 0
          } suffix="ms" color="text-slate-700" />
          <MetricCard label="P95 延迟" value={m.latency_p95 ?? 0} suffix="ms" color="text-amber-600" />
          <MetricCard label="P99 延迟" value={m.latency_p99 ?? 0} suffix="ms" color="text-rose-600" />
        </div>
      </div>

      {/* 评测历史 */}
      <div className="bg-white rounded-lg border border-slate-200 p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">评测历史</h3>
        {runs.length === 0 && (
          <div className="text-center py-6 text-slate-400 text-sm">暂无评测记录</div>
        )}
        <div className="space-y-2">
          {runs.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelectedRun(r)}
              className={`w-full text-left p-3 rounded-lg border transition ${
                selectedRun?.id === r.id ? "border-indigo-500 bg-indigo-50" : "border-slate-200 hover:bg-slate-50"
              }`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-slate-800">实验 #{r.id} · {r.name}</div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    {new Date(r.started_at).toLocaleString()}
                  </div>
                </div>
                <div className="text-right">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    r.status === "success" ? "bg-emerald-100 text-emerald-700" :
                    r.status === "running" ? "bg-amber-100 text-amber-700" :
                    "bg-rose-100 text-rose-700"
                  }`}>
                    {r.status}
                  </span>
                  {r.metrics_json?.AUC !== undefined && (
                    <div className="text-xs text-slate-500 mt-1">AUC={r.metrics_json.AUC.toFixed(3)}</div>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
