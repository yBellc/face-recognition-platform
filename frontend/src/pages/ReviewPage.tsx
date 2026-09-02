import { useEffect, useState } from "react";
import api from "../api";
import { deleteProbe, exportCandidateResults, getPreferredProjectId, getProbe, getProbeDiagnostics, listProjects, mediaUrl, notifyProjectChange, projectLabel, ProbeDetail, ProbeDiagnostic, Project } from "../api";

interface Candidate {
  id: number;
  probe_id: number;
  probe_face_id: number;
  subject_id: number;
  subject_code: string;
  similarity: number;
  decision_band: string;
  rank: number;
  status: string;
  review_task_id: number | null;
}

interface ProbeInfo {
  id: number;
  object_uri: string;
  processing_ms: number | null;
  processing_status: string;
  candidate_count?: number;
  archived_at?: string | null;
}

interface RefThumb {
  id: number;
  subject_id: number;
  quality_score?: number;
  object_uri: string;
}

interface Props {
  projectId: number;
}

type Decision = "confirm" | "exclude" | "uncertain";

// 同一张图片内的人脸颜色是稳定的：人脸 1 蓝、人脸 2 紫、人脸 3 橙、人脸 4 绿。
// 左侧框选、右侧人脸切换和候选卡片都从这里取色，避免多人人脸对应错位。
const FACE_COLORS = ["#0ea5e9", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444"];

export default function ReviewPage({ projectId }: Props) {
  // 兼容侧栏进入、识别页新开复核页两种地址：BrowserRouter 使用 search，旧链接可能把参数放在 hash。
  const queryText = window.location.search || (window.location.hash.includes("?") ? `?${window.location.hash.split("?")[1]}` : "");
  const hashQuery = new URLSearchParams(queryText);
  const requestedProjectId = Number(hashQuery.get("project_id"));
  const requestedProbeId = Number(hashQuery.get("probe_id"));
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState(Number.isFinite(requestedProjectId) && requestedProjectId > 0 ? requestedProjectId : getPreferredProjectId(projectId));
  const [probes, setProbes] = useState<ProbeInfo[]>([]);
  const [selectedProbe, setSelectedProbe] = useState<ProbeInfo | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [refImages, setRefImages] = useState<RefThumb[]>([]);
  const [diagnostics, setDiagnostics] = useState<ProbeDiagnostic[]>([]);
  const [probeDetail, setProbeDetail] = useState<ProbeDetail | null>(null);
  const [selectedFaceId, setSelectedFaceId] = useState<number | null>(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [deciding, setDeciding] = useState(false);
  const [error, setError] = useState("");
  const [probePage, setProbePage] = useState(0);
  const [showArchived, setShowArchived] = useState(false);
  const [exporting, setExporting] = useState(false);
  const pageSize = 8;

  const loadProbes = async () => {
    try {
      const r = await api.get("/api/v1/probes/list", { params: { project_id: activeProjectId, limit: 50, include_archived: showArchived } });
      const list = ((r.data || []) as ProbeInfo[]).filter((p) => showArchived ? Boolean(p.archived_at) : !p.archived_at);
      // Enrich with candidate count
      const enriched = await Promise.all(
        list.map(async (p) => {
          try {
            const cr = await api.get("/api/v1/candidates", { params: { probe_id: p.id } });
            return { ...p, candidate_count: (cr.data || []).length };
          } catch {
            return { ...p, candidate_count: 0 };
          }
        })
      );
      setProbes(enriched);
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  const archiveSelectedProbe = async () => {
    if (!selectedProbe) return;
    try {
      await api.post(`/api/v1/probes/${selectedProbe.id}/archive`);
      setSelectedProbe(null); setProbePage(0); await loadProbes();
    } catch (e: any) { setError(e.response?.data?.detail || "归档失败"); }
  };

  const deleteSelectedProbe = async () => {
    if (!selectedProbe || !selectedProbe.archived_at) return;
    if (!window.confirm(`确定永久删除图片“${fileName(selectedProbe.object_uri)}”及其检测、候选和复核记录吗？此操作不可恢复。`)) return;
    try {
      await deleteProbe(selectedProbe.id);
      setSelectedProbe(null); setProbePage(0); await loadProbes();
    } catch (e: any) { setError(e.response?.data?.detail || "删除失败"); }
  };

  const exportSelectedProbe = async () => {
    if (!selectedProbe) return;
    setExporting(true); setError("");
    try { await exportCandidateResults({ probeId: selectedProbe.id }); }
    catch (e: any) { setError(e.response?.data?.detail || "单张图片结果导出失败"); }
    finally { setExporting(false); }
  };

  const loadCandidates = async (probeId: number) => {
    try {
      const [r, d] = await Promise.all([
        api.get("/api/v1/candidates", { params: { probe_id: probeId } }),
        getProbeDiagnostics(probeId),
      ]);
      const list = (r.data || []) as Candidate[];
      setCandidates(list);
      setDiagnostics(d.faces || []);
      // 每次打开新图片都从该图片的第一张人脸开始，不能复用上一张图片的 face id。
      const initialFaceId = d.faces?.[0]?.probe_face_id
        ?? list[0]?.probe_face_id
        ?? null;
      setSelectedFaceId(initialFaceId);
      const firstForFace = initialFaceId == null
        ? null
        : list.find((candidate) => candidate.probe_face_id === initialFaceId) || null;
      if (firstForFace) {
        setSelectedCandidate(firstForFace);
        loadRefImages(firstForFace.subject_id);
      } else {
        setSelectedCandidate(null);
        setRefImages([]);
      }
    } catch {}
  };

  const loadRefImages = async (subjectId: number) => {
    try {
      const r = await api.get(`/api/v1/subjects/${subjectId}/references`);
      setRefImages(r.data || []);
    } catch {
      setRefImages([]);
    }
  };

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
      if (Number.isFinite(id) && id > 0) { setActiveProjectId(id); setSelectedProbe(null); }
    };
    window.addEventListener("face-project-change", onProjectChange);
    return () => window.removeEventListener("face-project-change", onProjectChange);
  }, []);

  useEffect(() => {
    setSelectedProbe(null);
    setCandidates([]);
    setProbePage(0);
    loadProbes();
  }, [activeProjectId, showArchived]);

  const visibleProbes = probes.slice(probePage * pageSize, (probePage + 1) * pageSize);
  const totalProbePages = Math.max(1, Math.ceil(probes.length / pageSize));

  useEffect(() => {
    if (probes.length > 0 && !selectedProbe) {
      setSelectedProbe(probes.find((p) => p.id === requestedProbeId) || probes[0]);
    }
  }, [probes]);

  useEffect(() => {
    if (selectedProbe) {
      setCandidates([]); setDiagnostics([]); setSelectedCandidate(null); setRefImages([]); setSelectedFaceId(null);
      loadCandidates(selectedProbe.id);
      getProbe(selectedProbe.id).then((detail) => {
        setProbeDetail(detail);
        setSelectedFaceId(detail.detections?.[0]?.id ?? null);
        setImageSize({ width: 0, height: 0 });
      }).catch(() => setProbeDetail(null));
    } else {
      setProbeDetail(null);
      setSelectedFaceId(null);
    }
  }, [selectedProbe]);

  const selectedDetection = probeDetail?.detections?.find((d) => d.id === selectedFaceId) || probeDetail?.detections?.[0];
  const visibleCandidates = selectedFaceId
    ? candidates.filter((c) => c.probe_face_id === selectedFaceId)
    : candidates;
  const faceColor = (faceId: number | null | undefined, fallbackIndex = 0) => {
    const index = faceId == null ? fallbackIndex : (probeDetail?.detections?.findIndex((d) => d.id === faceId) ?? -1);
    return FACE_COLORS[(index >= 0 ? index : fallbackIndex) % FACE_COLORS.length];
  };

  const chooseFace = (faceId: number) => {
    setSelectedFaceId(faceId);
    const first = candidates.find((candidate) => candidate.probe_face_id === faceId) || null;
    setSelectedCandidate(first);
    if (first) loadRefImages(first.subject_id);
    else setRefImages([]);
  };

  const handleDecision = async (decision: Decision) => {
    if (!selectedCandidate) return;
    setDeciding(true);
    setError("");
    try {
      await api.post(`/api/v1/candidates/${selectedCandidate.id}/review`, { decision });
      // Refresh
      loadCandidates(selectedProbe!.id);
      loadProbes();
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setDeciding(false);
    }
  };

  const statusLabel = (s: string) => {
    const map: Record<string, string> = {
      pending: "待复核",
      confirmed: "已确认",
      excluded: "已排除",
      uncertain: "存疑",
    };
    return map[s] || s;
  };

  const fileName = (uri: string) => {
    try {
      // Remove file:// prefix if present
      const path = uri.replace(/^file:\/\//, '');
      // Handle both Unix and Windows paths
      const parts = path.split(/[\\/]/);
      return parts.pop() || uri;
    } catch {
      return uri;
    }
  };

  return (
    <div className="space-y-3">
      <div className="bg-white rounded-lg border border-slate-200 p-3 flex flex-wrap items-center gap-3">
        <div>
          <div className="text-xs text-slate-500">当前工作项目</div>
          <div className="text-sm text-slate-700 mt-0.5">只查看当前项目的上传记录和候选结果</div>
        </div>
        <select
          className="border border-slate-300 rounded-md px-3 py-2 text-sm min-w-64"
          value={activeProjectId}
          onChange={(e) => { const id = Number(e.target.value); notifyProjectChange(id); }}
        >
          {projects.length === 0 && <option value={activeProjectId}>项目 #{activeProjectId}</option>}
          {projects.map((p) => <option key={p.id} value={p.id}>{projectLabel(p)}（#{p.id}）</option>)}
        </select>
        <a href="/datasets" className="btn-secondary whitespace-nowrap text-xs">管理项目</a>
      </div>
      <div className="grid min-h-0 grid-cols-12 gap-4 h-[calc(100vh-250px)]">
      {/* 左侧: Probe 列表 */}
      <div className="col-span-3 min-h-0 bg-white rounded-lg border border-slate-200 flex flex-col">
        <div className="p-3 border-b border-slate-100">
          <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-700">{showArchived ? "已归档图片" : "待复核图片"}</h3><button type="button" className="text-xs text-indigo-600 hover:text-indigo-800" onClick={() => { setShowArchived((v) => !v); setProbePage(0); }}>{showArchived ? "查看待复核" : "查看已归档"}</button></div>
          <span className="text-xs text-slate-500">{probes.length} 张</span>
        </div>
        <div className="flex-1 overflow-auto p-2 space-y-2">
          {probes.length === 0 && (
            <div className="text-center text-xs text-slate-400 py-6">暂无待复核</div>
          )}
          {visibleProbes.map((p) => (
            <button
              key={p.id}
              onClick={() => setSelectedProbe(p)}
              className={`w-full text-left p-3 rounded-lg border transition ${
                selectedProbe?.id === p.id ? "border-indigo-500 bg-indigo-50" : "border-slate-200 hover:bg-slate-50"
              }`}
            >
              <div className="text-xs text-slate-500">#{p.id}</div>
              <div className="text-sm font-medium text-slate-800 truncate">
                {fileName(p.object_uri)}
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-slate-500">{p.candidate_count || 0} 候选</span>
                {p.processing_ms && (
                  <span className="text-xs text-slate-400">{p.processing_ms}ms</span>
                )}
                {p.archived_at && <span className="chip bg-slate-100 text-slate-500">已归档</span>}
              </div>
            </button>
          ))}
        </div>
        <div className="flex items-center justify-between border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
          <span>{probes.length ? `${probePage * pageSize + 1}-${Math.min((probePage + 1) * pageSize, probes.length)} / ${probes.length}` : "0 条"}</span>
          <div className="flex gap-1"><button className="btn-ghost !px-2 !py-1" disabled={probePage === 0} onClick={() => setProbePage((p) => Math.max(0, p - 1))}>‹</button><span className="px-1 py-1">{probePage + 1}/{totalProbePages}</span><button className="btn-ghost !px-2 !py-1" disabled={probePage >= totalProbePages - 1} onClick={() => setProbePage((p) => Math.min(totalProbePages - 1, p + 1))}>›</button></div>
        </div>
      </div>

      {/* 中间: 图片 */}
      <div className="col-span-5 min-h-0 bg-white rounded-lg border border-slate-200 flex flex-col overflow-hidden">
        <div className="p-3 border-b border-slate-100 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-700">现场图片 · 人脸定位</h3>
            <p className="text-xs text-slate-400 mt-0.5">点击彩色编号切换右侧对应候选</p>
          </div>
            <div className="flex items-center gap-2">{probeDetail && <span className="tag">已检测 {probeDetail.detections.length} 张人脸</span>}{selectedProbe && <><button className="btn-ghost !px-2 !py-1 text-xs" onClick={exportSelectedProbe} disabled={exporting}>{exporting ? "导出中…" : "导出此图"}</button>{!selectedProbe.archived_at && <button className="btn-ghost !px-2 !py-1 text-xs" onClick={archiveSelectedProbe}>归档此图片</button>}{selectedProbe.archived_at && <button className="btn-ghost !px-2 !py-1 text-xs text-rose-600 hover:border-rose-200 hover:bg-rose-50" onClick={deleteSelectedProbe}>永久删除</button>}</>}</div>
        </div>
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {!selectedProbe && (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm">
              选择左侧图片开始复核
            </div>
          )}
          {selectedProbe && (
            <div>
              <div className="text-xs text-slate-500 mb-2">原图</div>
              <div className="review-image-frame relative inline-block max-w-full bg-slate-100 rounded-xl border border-slate-200 overflow-visible">
                <img
                  src={mediaUrl(`/api/v1/probes/${selectedProbe.id}/preview`)}
                  alt="probe"
                  className="block max-w-full max-h-[520px] rounded-xl"
                  onLoad={(e) => setImageSize({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })}
                  onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0.3"; }}
                />
                {probeDetail && imageSize.width > 0 && probeDetail.detections.map((d, index) => {
                  const b = (d as any).bbox || {};
                  const rawX = Number(b.x || 0);
                  const rawY = Number(b.y || 0);
                  const rawW = Number(b.w || 0);
                  const rawH = Number(b.h || 0);
                  const xPercent = Math.max(0, Math.min(100, (rawX / imageSize.width) * 100));
                  const yPercent = Math.max(0, Math.min(100, (rawY / imageSize.height) * 100));
                  const widthPercent = Math.max(0.5, Math.min(100 - xPercent, (rawW / imageSize.width) * 100));
                  const heightPercent = Math.max(0.5, Math.min(100 - yPercent, (rawH / imageSize.height) * 100));
                  const labelOnInside = yPercent < 12;
                  const labelAlignRight = xPercent + widthPercent > 78;
                  const isSelected = d.id === (selectedDetection?.id ?? selectedFaceId);
                  const color = faceColor(d.id, index);
                  return (
                    <button
                      key={d.id}
                      type="button"
                      aria-label={`选择人脸 ${index + 1}`}
                      onClick={() => chooseFace(d.id)}
                      className={`absolute transition-all duration-200 ${isSelected ? "z-20" : "z-10 opacity-70 hover:opacity-100"}`}
                      style={{
                        left: `${xPercent}%`,
                        top: `${yPercent}%`,
                        width: `${widthPercent}%`,
                        height: `${heightPercent}%`,
                        border: `${isSelected ? 3 : 2}px solid ${color}`,
                        background: isSelected ? `${color}22` : "transparent",
                      }}
                    >
                      <span className={`absolute whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-bold text-white shadow ${labelOnInside ? "top-1" : "-top-7"} ${labelAlignRight ? "right-0 left-auto" : "left-0"}`} style={{ background: color }}>
                        人脸 {index + 1} · {diagnostics.find((diag) => diag.probe_face_id === d.id)?.usable === false
                          ? "无法判断"
                          : candidates.find((candidate) => candidate.probe_face_id === d.id)?.subject_code || "未匹配"}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 右侧: 候选 + 参考图 + 操作 */}
      <div className="col-span-4 min-h-0 bg-white rounded-lg border border-slate-200 flex flex-col overflow-hidden">
        <div className="p-3 border-b border-slate-100">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-700">匹配结果 · 逐人复核</h3>
              <p className="text-xs text-slate-400 mt-0.5">每个彩色人脸框对应一组候选</p>
            </div>
            {probeDetail && <span className="tag">{visibleCandidates.length} 个候选</span>}
          </div>
          {probeDetail && probeDetail.detections.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {probeDetail.detections.map((d, i) => (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => chooseFace(d.id)}
                  className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${selectedFaceId === d.id ? "text-white shadow-sm" : "text-slate-600 hover:text-slate-900"}`}
                  style={{
                    background: selectedFaceId === d.id ? faceColor(d.id, i) : `${faceColor(d.id, i)}18`,
                    border: `1px solid ${faceColor(d.id, i)}55`,
                  }}
                >
                  {diagnostics.find((diag) => diag.probe_face_id === d.id)?.usable === false
                    ? `人脸 ${i + 1} · 无法判断`
                    : `人脸 ${i + 1} · ${candidates.filter((c) => c.probe_face_id === d.id).length} 候选`}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex-1 overflow-auto p-3 space-y-3">
          {!selectedProbe && (
            <div className="text-xs text-slate-400">选择图片后显示候选</div>
          )}
          {selectedProbe && selectedDetection && visibleCandidates.length === 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              {diagnostics.find((diag) => diag.probe_face_id === selectedDetection.id)?.usable === false
                ? "当前人脸质量不足（模糊、侧脸、遮挡或逆光），系统不会强行匹配，标记为“无法判断”。"
                : "当前人脸没有达到最低相似度阈值，暂不判定为重点关注对象。"}
            </div>
          )}
          {visibleCandidates.map((c) => {
            const isSel = selectedCandidate?.id === c.id;
            const candidateColor = faceColor(c.probe_face_id);
            const decided = c.status !== "pending";
            return (
              <button
                key={c.id}
                type="button"
                className={`p-3 rounded-lg border cursor-pointer transition ${
                  isSel ? "shadow-sm" : "border-slate-200 hover:bg-slate-50"
                } ${decided ? "opacity-60" : ""}`}
                style={isSel ? { borderColor: candidateColor, background: `${candidateColor}12` } : undefined}
                onClick={() => {
                  setSelectedFaceId(c.probe_face_id);
                  setSelectedCandidate(c);
                  loadRefImages(c.subject_id);
                }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-bold text-white px-2 py-0.5 rounded" style={{ background: candidateColor }}>
                    #{c.rank}
                  </span>
                  <span className="h-2 w-2 rounded-full" style={{ background: candidateColor }} aria-hidden="true" />
                  <span className="font-medium text-sm text-slate-800">{c.subject_code}</span>
                  <span className="ml-auto text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                    {statusLabel(c.status)}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full"
                      style={{ width: `${Math.max(0, c.similarity * 100)}%`, background: candidateColor }}
                    />
                  </div>
                  <span className="text-xs font-mono text-slate-700">{c.similarity.toFixed(4)}</span>
                </div>
              </button>
            );
          })}

          {/* 参考图预览 */}
          {selectedCandidate && selectedCandidate.probe_face_id === selectedFaceId && refImages.length > 0 && (
            <div className="mt-4 pt-4 border-t border-slate-100">
              <div className="text-xs text-slate-500 mb-2">参考照片</div>
              <div className="grid grid-cols-3 gap-2">
                {refImages.map((ref) => (
                  <div key={ref.id} className="aspect-square bg-slate-100 rounded overflow-hidden">
                    <img
                      src={mediaUrl(`/api/v1/references/${ref.id}/thumb`)}
                      alt={`ref-${ref.id}`}
                      className="w-full h-full object-cover"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {selectedProbe && diagnostics.length > 0 && (
            <div className="mt-4 pt-4 border-t border-slate-100">
              <div className="text-xs font-medium text-slate-600 mb-2">匹配过程说明</div>
              <div className="space-y-2">
                {diagnostics.map((d, i) => {
                  const nearest = d.best_candidates?.[0];
                  return (
                    <div key={d.probe_face_id} className="rounded bg-slate-50 px-3 py-2 text-xs text-slate-500">
                      <span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: faceColor(d.probe_face_id, i) }} aria-hidden="true" />
                      人脸 {i + 1}：{d.usable === false ? <span className="font-semibold text-amber-700">无法判断</span> : nearest ? <>最近对象 <span className="font-medium text-slate-700">{nearest.subject_code}</span>，相似度 {nearest.similarity.toFixed(4)}</> : "没有可比较的对象"}；{d.reason}。
                      {d.threshold_low != null && <span> 最低阈值 {d.threshold_low.toFixed(2)}。</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* 操作按钮 */}
        <div className="sticky bottom-0 p-3 border-t border-slate-100 bg-white shadow-[0_-6px_16px_rgba(15,23,42,0.06)]">
          {selectedCandidate && selectedCandidate.status === "pending" && (
            <div className="grid grid-cols-3 gap-2">
              <button
                onClick={() => handleDecision("exclude")}
                disabled={deciding}
                className="px-3 py-2 text-xs bg-rose-100 text-rose-700 rounded hover:bg-rose-200 disabled:opacity-50"
              >
                ✕ 排除
              </button>
              <button
                onClick={() => handleDecision("uncertain")}
                disabled={deciding}
                className="px-3 py-2 text-xs bg-slate-100 text-slate-700 rounded hover:bg-slate-200 disabled:opacity-50"
              >
                ? 存疑
              </button>
              <button
                onClick={() => handleDecision("confirm")}
                disabled={deciding}
                className="px-3 py-2 text-xs bg-emerald-100 text-emerald-700 rounded hover:bg-emerald-200 disabled:opacity-50"
              >
                ✓ 确认
              </button>
            </div>
          )}
          {!selectedCandidate && selectedProbe && (
            <div className="text-center text-xs text-slate-400 py-2">先选择右侧候选，再记录复核结论</div>
          )}
          {selectedCandidate && selectedCandidate.status !== "pending" && (
            <div className="text-center text-xs text-slate-500 py-2">
              已标记为 {statusLabel(selectedCandidate.status)}
            </div>
          )}
          {error && <div className="mt-2 text-xs text-rose-600">⚠ {error}</div>}
        </div>
      </div>
      </div>
    </div>
  );
}
