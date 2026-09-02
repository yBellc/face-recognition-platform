import { useEffect, useState } from "react";
import api from "../api";
import { getPreferredProjectId, getProbeDiagnostics, listProjects, notifyProjectChange, projectLabel, ProbeDiagnostic, Project } from "../api";

interface Candidate {
  id: number;
  probe_face_id: number;
  rank: number;
  subject_code: string;
  similarity: number;
  decision_band: string;
}

interface Props {
  projectId: number;
}

export default function ImageRecognitionPage({ projectId }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState(getPreferredProjectId(projectId));
  const [file, setFile] = useState<File | null>(null);
  const [processing, setProcessing] = useState(false);
  const [probeResult, setProbeResult] = useState<{
    probe_id: number;
    faces: Array<{ id: number; bbox: number[]; quality: number | null; candidates: Candidate[]; diagnostic?: ProbeDiagnostic }>;
    candidates: Candidate[];
    image_url?: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [selectedFaceId, setSelectedFaceId] = useState<number | null>(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [previewUrl, setPreviewUrl] = useState("");

  useEffect(() => {
    if (!file) {
      setPreviewUrl("");
      setImageSize({ width: 0, height: 0 });
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    listProjects().then((items) => {
      setProjects(items || []);
      const preferred = getPreferredProjectId(items?.[0]?.id ?? projectId);
      const next = items?.find((item) => item.id === preferred)?.id ?? items?.[0]?.id ?? projectId;
      if (next !== activeProjectId) setActiveProjectId(next);
      notifyProjectChange(next);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const onProjectChange = (event: Event) => {
      const id = Number((event as CustomEvent).detail);
      if (Number.isFinite(id) && id > 0) { setActiveProjectId(id); setProbeResult(null); }
    };
    window.addEventListener("face-project-change", onProjectChange);
    return () => window.removeEventListener("face-project-change", onProjectChange);
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setProcessing(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("project_id", String(activeProjectId));
      fd.append("source_type", "folder");
      fd.append("async_mode", "false");
      fd.append("file", file);
      const resp = await api.post("/api/v1/probes/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });
      const pid = resp.data.probe_id;

      // 轮询真实处理状态，避免固定等待时间导致慢图仍在 processing 时读到空结果。
      let latest: any = null;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        latest = (await api.get(`/api/v1/probes/${pid}`)).data;
        if (latest?.processing_status === "processed" || latest?.processing_status === "failed") break;
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
      if (latest?.processing_status === "failed") {
        throw new Error(latest.error_message || "图片处理失败，请重试");
      }
      if (latest?.processing_status !== "processed") {
        throw new Error("图片处理超时，请到“识别结果与复核”查看处理状态");
      }

      // 同时读取人脸检测详情和候选，把一张图片中的每张脸分别展示。
      const [detailResp, candResp, diagnosticResp] = await Promise.all([
        api.get(`/api/v1/probes/${pid}`),
        api.get(`/api/v1/candidates`, { params: { probe_id: pid } }),
        getProbeDiagnostics(pid),
      ]);
      const allCandidates: Candidate[] = candResp.data || [];
      const diagnostics = new Map((diagnosticResp.faces || []).map((d) => [d.probe_face_id, d]));
      const faces = (detailResp.data?.detections || []).map((d: any) => {
        const b = d.bbox || {};
        return {
          id: d.id,
          bbox: [b.x || 0, b.y || 0, b.w || 0, b.h || 0],
          quality: d.quality_score,
          candidates: allCandidates.filter((c) => c.probe_face_id === d.id),
          diagnostic: diagnostics.get(d.id),
        };
      });
      setProbeResult({
        probe_id: pid,
        faces,
        candidates: allCandidates,
      });
      setSelectedFaceId(faces[0]?.id ?? null);
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setProcessing(false);
    }
  };

  const bandStyle = (band: string) => {
    switch (band) {
      case "high": return { bg: "bg-emerald-500", text: "text-emerald-700", label: "高置信" };
      case "medium": return { bg: "bg-amber-500", text: "text-amber-700", label: "中等" };
      case "low": return { bg: "bg-sky-500", text: "text-sky-700", label: "低置信" };
      default: return { bg: "bg-slate-300", text: "text-slate-600", label: "拒绝" };
    }
  };

  const faceColors = [
    { border: "#38bdf8", bg: "rgba(14, 165, 233, 0.18)", solid: "#0284c7" },
    { border: "#a78bfa", bg: "rgba(139, 92, 246, 0.18)", solid: "#7c3aed" },
    { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.18)", solid: "#d97706" },
    { border: "#34d399", bg: "rgba(16, 185, 129, 0.18)", solid: "#059669" },
  ];
  const selectedFace = probeResult?.faces.find((face) => face.id === selectedFaceId) || probeResult?.faces[0];

  return (
    <div className="space-y-6 pb-8">
      {/* 上传区 */}
      <div className="relative overflow-hidden bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 rounded-2xl border border-indigo-900/60 p-6 text-white shadow-xl shadow-indigo-950/10">
        <div className="pointer-events-none absolute -right-16 -top-20 w-64 h-64 rounded-full bg-indigo-500/20 blur-3xl" />
        <div className="pointer-events-none absolute right-32 -bottom-24 w-52 h-52 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-3 mb-3">
          <div>
            <div className="flex items-center gap-2 text-xs text-indigo-200 uppercase tracking-[0.2em]"><span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" /> LIVE MATCH</div>
            <h2 className="text-2xl font-semibold text-white mt-1">现场图片智能识别</h2>
            <p className="text-sm text-slate-300 mt-1">一张图片多人脸逐一定位，点击人脸框查看对应候选与匹配依据</p>
          </div>
          <div className="relative z-10">
            <div className="mb-1 text-[10px] uppercase tracking-[0.16em] text-indigo-200">当前识别任务</div>
            <select
              aria-label="当前识别任务"
              title="选择要使用的对象库"
              className="border border-white/20 bg-white/10 text-white rounded-lg px-3 py-2 text-sm min-w-64 backdrop-blur focus:ring-2 focus:ring-cyan-300/50"
              value={activeProjectId}
              onChange={(e) => { const id = Number(e.target.value); notifyProjectChange(id); setProbeResult(null); }}
            >
              {projects.length === 0 && <option value={activeProjectId}>项目 #{activeProjectId}</option>}
              {projects.map((p) => <option className="text-slate-800" key={p.id} value={p.id}>{projectLabel(p)}（#{p.id}）</option>)}
            </select>
            <a href="/datasets" className="mt-1 inline-flex text-[11px] text-cyan-200/80 hover:text-white">找不到项目？去项目管理 →</a>
          </div>
        </div>
        <div className="relative z-10 flex flex-col md:flex-row gap-4">
          <label className="relative flex-1 border border-white/20 bg-white/5 rounded-xl p-8 text-center cursor-pointer hover:border-cyan-300/70 hover:bg-white/10 transition-all duration-300 group">
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                if (e.target.files?.[0]) {
                  setFile(e.target.files[0]);
                  setProbeResult(null);
                }
              }}
            />
            <div className="text-4xl mb-2 transition-transform duration-300 group-hover:scale-110">🖼️</div>
            <div className="text-sm text-slate-100">
              {file ? file.name : "点击选择待识别图片"}
            </div>
            <div className="text-xs text-slate-400 mt-1">支持 JPG / PNG；一张图片可识别多张人脸，最大 10MB</div>
          </label>
          <div className="flex flex-col gap-2">
            <button
              onClick={handleUpload}
              disabled={!file || processing}
              className="bg-cyan-400 text-slate-950 font-semibold text-sm px-6 py-2.5 rounded-lg hover:bg-cyan-300 disabled:opacity-40 transition-all shadow-lg shadow-cyan-500/20"
            >
              {processing ? "识别中..." : "🔍 开始识别"}
            </button>
            {probeResult && (
              <button
                className="text-xs px-3 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-white border border-white/10"
                onClick={() => {
                  window.open(`/review?project_id=${activeProjectId}&probe_id=${probeResult.probe_id}`, "_blank");
                }}
              >
                前往复核 →
              </button>
            )}
          </div>
        </div>
        {error && <div className="mt-3 text-xs text-rose-200 bg-rose-500/20 border border-rose-300/20 rounded-lg px-3 py-2">⚠ {error}</div>}
      </div>

      {probeResult && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 animate-[fadeIn_0.4s_ease-out]">
          {[
            ["检测人脸", `${probeResult.faces.length}`, "本张图片"],
            ["重点候选", `${probeResult.candidates.length}`, "待复核"],
            ["最高相似度", probeResult.candidates.length ? Math.max(...probeResult.candidates.map((c) => c.similarity)).toFixed(4) : "—", "当前结果"],
            ["处理编号", `#${probeResult.probe_id}`, "可追溯"],
          ].map(([label, value, hint]) => (
            <div key={label} className="bg-white rounded-xl border border-slate-200 px-4 py-3 shadow-sm hover:-translate-y-0.5 transition-transform">
              <div className="text-[11px] uppercase tracking-wider text-slate-400">{label}</div>
              <div className="text-xl font-semibold text-slate-800 mt-1">{value}</div>
              <div className="text-[11px] text-slate-400 mt-0.5">{hint}</div>
            </div>
          ))}
        </div>
      )}

      {/* 原图 + 人脸框预览 */}
      {file && (
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-800">人脸定位与选择</h3>
              <p className="text-xs text-slate-400 mt-0.5">点击图片中的彩色框，或点击下方人脸卡片查看对应结果</p>
            </div>
            {probeResult && <span className="text-xs text-slate-500">已定位 {probeResult.faces.length} 张人脸</span>}
          </div>
          <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0">
          <div className="recognition-image-frame relative inline-block max-w-full overflow-hidden rounded-xl bg-slate-950">
            <img
              src={previewUrl}
              alt="probe"
              className="block max-w-full max-h-[560px] rounded-xl"
              onLoad={(e) => setImageSize({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })}
            />
            {processing && (
              <div className="absolute inset-0 bg-slate-950/55 backdrop-blur-[1px] flex items-center justify-center rounded-xl">
                <div className="text-center text-white animate-pulse">
                  <div className="text-3xl">◌</div>
                  <div className="text-sm mt-2 tracking-wide">InsightFace 正在扫描人脸…</div>
                </div>
              </div>
            )}
            {probeResult && imageSize.width > 0 && probeResult.faces.map((face, index) => {
              const color = faceColors[index % faceColors.length];
              const isSelected = face.id === (selectedFace?.id ?? selectedFaceId);
              const candidate = face.candidates[0];
              const nearest = face.diagnostic?.best_candidates?.[0];
              const label = candidate?.subject_code || nearest?.subject_code || `人脸 ${index + 1}`;
              const [x, y, w, h] = face.bbox;
              // 坐标来自原图，先限制在 0~100%，避免边缘人脸把标签裁到容器外。
              const xPct = Math.max(0, Math.min(100, (x / imageSize.width) * 100));
              const yPct = Math.max(0, Math.min(100, (y / imageSize.height) * 100));
              const wPct = Math.max(0.5, Math.min(100 - xPct, (w / imageSize.width) * 100));
              const hPct = Math.max(0.5, Math.min(100 - yPct, (h / imageSize.height) * 100));
              const labelInside = yPct < 13;
              const labelRight = xPct + wPct > 76;
              return (
                <button
                  key={face.id}
                  type="button"
                  aria-label={`选择人脸 ${index + 1}`}
                  onClick={() => setSelectedFaceId(face.id)}
                  className={`absolute face-box-scan transition-all duration-300 ${isSelected ? "z-20 scale-[1.02]" : "z-10 opacity-80 hover:opacity-100"}`}
                  style={{
                    left: `${xPct}%`,
                    top: `${yPct}%`,
                    width: `${wPct}%`,
                    height: `${hPct}%`,
                    border: `${isSelected ? 3 : 2}px solid ${color.border}`,
                    backgroundColor: isSelected ? color.bg : "transparent",
                    color: color.border,
                  }}
                >
                  <span
                    className={`absolute whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-semibold text-white shadow-lg ${labelInside ? "top-1" : "-top-7"} ${labelRight ? "right-0 left-auto" : "left-0"}`}
                    style={{ backgroundColor: color.solid, maxWidth: "min(180px, 28vw)", overflow: "hidden", textOverflow: "ellipsis" }}
                  >
                    #{index + 1} · {label}
                  </span>
                </button>
              );
            })}
          </div>
          </div>
          {probeResult && (
            <aside className="match-overview rounded-xl border border-slate-200 bg-slate-50/75 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">MATCH OVERVIEW</div>
                  <h4 className="mt-1 text-sm font-semibold text-slate-800">匹配过程总览</h4>
                </div>
                <span className="rounded-full bg-white px-2 py-1 text-[11px] text-slate-500">{probeResult.faces.length} 张人脸</span>
              </div>
              <div className="mt-3 space-y-2">
                {probeResult.faces.map((face, index) => {
                  const color = faceColors[index % faceColors.length];
                  const candidate = face.candidates[0];
                  const nearest = face.diagnostic?.best_candidates?.[0];
                  const subject = candidate?.subject_code || "未匹配";
                  const score = candidate?.similarity ?? nearest?.similarity;
                  const state = candidate ? "候选待复核" : (nearest ? "低于阈值" : "无法判断");
                  return (
                    <button key={face.id} type="button" onClick={() => setSelectedFaceId(face.id)} className="match-overview-row w-full rounded-lg border bg-white p-3 text-left transition hover:-translate-y-px hover:shadow-sm" style={{ borderColor: `${color.border}66` }}>
                      <div className="flex items-center gap-2">
                        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: color.solid, boxShadow: `0 0 0 3px ${color.bg}` }} />
                        <span className="text-xs font-semibold text-slate-700">人脸 {index + 1}</span>
                        <span className="ml-auto text-[11px] text-slate-400">{state}</span>
                      </div>
                      <div className="mt-2 flex items-baseline justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-slate-800">{subject}</span>
                        <span className="font-mono text-xs text-slate-500">{score != null ? score.toFixed(4) : "—"}</span>
                      </div>
                      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full" style={{ width: `${score != null ? Math.max(0, Math.min(100, score * 100)) : 0}%`, backgroundColor: color.solid }} /></div>
                      <div className="mt-2 text-[11px] text-slate-400">{candidate ? "已达到最低阈值，进入人工复核" : nearest ? `最近候选 ${nearest.subject_code}，未达到最低阈值` : "质量不足或未生成可比对特征"}</div>
                    </button>
                  );
                })}
              </div>
              <div className="mt-3 border-t border-slate-200 pt-3 text-[11px] leading-5 text-slate-400">点击任意行可定位图片中的对应颜色框；所有人脸同时保留在此处，不会因切换而丢失匹配依据。</div>
            </aside>
          )}
          </div>
        </div>
      )}

      {/* 每张人脸的候选结果 */}
      {probeResult && (
        <div className="bg-white rounded-lg border border-slate-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-700">
              检测结果 ({probeResult.faces.length} 张人脸)
            </h3>
            <span className="text-xs text-slate-500">点击卡片可切换图片中的人脸</span>
          </div>
          <div className="space-y-2">
            {probeResult.faces.map((face, index) => {
              const c = face.candidates[0];
              const nearest = face.diagnostic?.best_candidates?.[0];
              const bs = c ? bandStyle(c.decision_band) : bandStyle("rejected");
              const isSelected = face.id === (selectedFace?.id ?? selectedFaceId);
              const bandColor = c?.decision_band === "high" ? "#059669" : c?.decision_band === "medium" ? "#d97706" : c?.decision_band === "low" ? "#0284c7" : "#64748b";
              return (
                <div key={face.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedFaceId(face.id)}
                    className={`w-full text-left flex items-center gap-3 p-3 rounded-xl border transition-all duration-300 ${isSelected ? "bg-indigo-50/60 shadow-sm" : "border-slate-200 hover:border-indigo-200 hover:bg-slate-50"}`}
                    style={isSelected ? { borderColor: faceColors[index % faceColors.length].border } : undefined}
                  >
                  <div className="w-10 h-10 rounded-full flex items-center justify-center text-white font-medium text-sm" style={{ backgroundColor: faceColors[index % faceColors.length].solid }}>
                    #{index + 1}
                  </div>
                  <div className="flex-1">
                    <div className="font-medium text-sm text-slate-800">{c ? c.subject_code : "未匹配"}</div>
                    {c ? <div className="flex items-center gap-2 mt-1">
                        <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                          <div className="h-full" style={{ width: `${Math.max(0, c.similarity * 100)}%`, backgroundColor: faceColors[index % faceColors.length].solid }} />
                        </div>
                        <span className="text-xs text-slate-600 font-mono">{c.similarity.toFixed(4)}</span>
                      </div> : <div className="text-xs text-slate-400 mt-1">没有超过当前验证阈值的人员</div>}
                  </div>
                  <span className="text-xs px-2 py-1 rounded-full" style={{ backgroundColor: `${bandColor}15`, color: bandColor }}>
                    {bs.label}
                  </span>
                  </button>
                  {!c && nearest && (
                  <div className="mt-2 ml-13 rounded bg-slate-50 px-3 py-2 text-xs text-slate-500">
                    最近候选：<span className="font-medium text-slate-700">{nearest.subject_code}</span>，相似度 {nearest.similarity.toFixed(4)}；低于最低阈值 {face.diagnostic?.threshold_low?.toFixed(2) ?? "—"}，所以未列为匹配结果。
                  </div>
                  )}
                </div>
              );
            })}
          </div>
          {selectedFace && (
            <div className="mt-4 rounded-xl border border-indigo-100 bg-gradient-to-r from-indigo-50 to-cyan-50 p-4 animate-[fadeIn_0.3s_ease-out]">
              <div className="flex items-center justify-between">
                <div className="text-xs font-semibold text-indigo-900">当前选中：人脸 {probeResult.faces.findIndex((f) => f.id === selectedFace.id) + 1}</div>
                <div className="text-[11px] text-indigo-600">可在图片中再次点击切换</div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3 text-xs">
                <div><span className="text-slate-500">候选对象</span><div className="font-semibold text-slate-800 mt-1">{selectedFace.candidates[0]?.subject_code || selectedFace.diagnostic?.best_candidates?.[0]?.subject_code || "未匹配"}</div></div>
                <div><span className="text-slate-500">相似度</span><div className="font-semibold text-slate-800 mt-1">{(selectedFace.candidates[0]?.similarity ?? selectedFace.diagnostic?.best_candidates?.[0]?.similarity)?.toFixed(4) ?? "—"}</div></div>
                <div><span className="text-slate-500">人脸质量</span><div className="font-semibold text-slate-800 mt-1">{selectedFace.quality?.toFixed(2) ?? "—"}</div></div>
                <div><span className="text-slate-500">处理结论</span><div className="font-semibold text-slate-800 mt-1">{selectedFace.candidates[0] ? "候选待复核" : "未达阈值"}</div></div>
              </div>
            </div>
          )}
          <div className="mt-4 text-xs text-slate-400">
            ⚠ 系统不自动确认身份，所有候选均需人工复核
          </div>
        </div>
      )}

      {probeResult && probeResult.faces.length === 0 && !processing && <div className="bg-white rounded-lg border border-slate-200 p-8 text-center text-slate-500"><div className="text-4xl mb-2">🔍</div><div>未检测到可用人脸</div><div className="text-xs mt-1">请更换清晰、正面或尺寸更大的人脸图片</div></div>}
    </div>
  );
}
