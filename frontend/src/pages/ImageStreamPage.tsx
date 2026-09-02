import { useEffect, useRef, useState } from "react";
import { listProjects, projectLabel, uploadProbe, ProbeDetail, getProbe, ProbeImage, listProbes } from "../api";

export default function ImageStreamPage() {
  const [projectId, setProjectId] = useState(1);
  const [projects, setProjects] = useState<Array<{ id: number; name: string }>>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [probeList, setProbeList] = useState<ProbeImage[]>([]);
  const [detail, setDetail] = useState<ProbeDetail | null>(null);
  const [bandFilter, setBandFilter] = useState<string>("all");
  const [onlyPending, setOnlyPending] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setLoadingProjects(true);
    listProjects()
      .then((arr) => {
        setProjects(arr);
        if (arr.length) setProjectId(arr[0].id);
      })
      .catch(() => setProjects([]))
      .finally(() => setLoadingProjects(false));
    // 初始加载
    listProbes({ limit: 30 }).then((r) => r && r.length && setProbeList(r)).catch(() => {});
  }, []);

  const shown = probeList
    .filter((p) => (onlyPending ? p.processing_status === "pending" || p.candidate_count > 0 : true))
    .slice(0, 32);

  const doUpload = async (sync: boolean) => {
    if (!file) return;
    setUploading(true);
    try {
      const r = await uploadProbe({ project_id: projectId, file, async: !sync });
      const probeId = r?.probe_id;
      if (probeId) {
        try {
          const full = await getProbe(probeId);
          setDetail(full);
        } catch { setDetail(null); }
        // 刷新列表
        try {
          const list = await listProbes({ limit: 30 });
          if (list.length) setProbeList(list);
        } catch {}
      }
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (e: any) {
      alert("上传失败：" + (e?.message || String(e)));
    } finally {
      setUploading(false);
    }
  };

  const openDetail = async (id: number) => {
    try {
      const d = await getProbe(id);
      setDetail(d);
    } catch { setDetail(null); }
  };

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      {/* 左列：上传 + 流 */}
      <div className="xl:col-span-2 space-y-4">
        {/* 上传卡片 */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">📤 上传待比对图片 (Probe)</span>
            <div className="flex items-center gap-2">
              <label className="label mr-2">项目</label>
              <select
                className="input w-40"
                value={projectId}
                onChange={(e) => setProjectId(Number(e.target.value))}
                disabled={loadingProjects}
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{projectLabel(p)}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="card-body space-y-3">
            <div
              className="border-2 border-dashed border-slate-300 rounded-lg p-6 text-center text-sm text-slate-500 hover:border-brand-500 hover:bg-brand-50 cursor-pointer"
              onClick={() => fileInputRef.current?.click()}
            >
              {file ? (
                <div className="flex items-center justify-center gap-3">
                  <span className="text-lg">✅</span>
                  <span className="font-medium text-slate-700">{file.name}</span>
                  <span className="tag">{(file.size / 1024).toFixed(0)} KB</span>
                </div>
              ) : (
                <div>
                  <div className="text-lg mb-1">📁 选择图片</div>
                  <div className="text-xs">支持 JPG/PNG，建议 640×480 以上；按项目隔离比对</div>
                </div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="flex gap-2 justify-end">
              <button className="btn-ghost" disabled={!file || uploading} onClick={() => doUpload(false)}>
                {uploading ? "正在入队…" : "异步入队"}
              </button>
              <button className="btn-primary" disabled={!file || uploading} onClick={() => doUpload(true)}>
                {uploading ? "处理中…" : "上传并立即比对"}
              </button>
            </div>
          </div>
        </div>

        {/* 流卡片 */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">🎞 图片流 (最近 32 张)</span>
            <div className="flex items-center gap-3">
              <label className="text-xs text-slate-500">
                <input type="checkbox" checked={onlyPending} onChange={(e) => setOnlyPending(e.target.checked)} className="mr-1" />
                只看待比对
              </label>
              <select className="input w-32" value={bandFilter} onChange={(e) => setBandFilter(e.target.value)}>
                <option value="all">全部决策带</option>
                <option value="high">High 高置信</option>
                <option value="medium">Medium 中置信</option>
                <option value="low">Low 低置信</option>
              </select>
            </div>
          </div>
          <div className="card-body">
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {shown.map((p) => (
                <div
                  key={p.id}
                  onClick={() => openDetail(p.id)}
                  className="group rounded-lg overflow-hidden border border-slate-200 bg-slate-50 hover:border-brand-500 hover:shadow-sm cursor-pointer transition"
                >
                  <div className="aspect-[4/3] bg-slate-200 relative flex items-center justify-center text-slate-400">
                    <span className="text-2xl">🖼</span>
                    <span className="absolute left-2 top-2 tag bg-white/80 backdrop-blur">#{p.id}</span>
                    <span className="absolute right-2 top-2">{
                      p.processing_status === "pending" ? <span className="status-pending">pending</span> :
                      p.processing_status === "failed" ? <span className="status-excluded">fail</span> :
                      <span className="band-high">✔</span>
                    }</span>
                  </div>
                  <div className="p-2 text-xs space-y-0.5">
                    <div className="flex justify-between text-slate-600">
                      <span>{new Date(p.created_at).toLocaleTimeString()}</span>
                      <span className="font-medium">{p.candidate_count} 候选</span>
                    </div>
                    <div className="text-slate-400 truncate">{p.object_key?.split("/").pop()}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 右列：详情 */}
      <div className="space-y-4">
        <div className="card sticky top-0">
          <div className="card-header">
            <span className="card-title">🔎 详情</span>
            {detail?.id && <span className="tag">#{detail.id}</span>}
          </div>
          <div className="card-body space-y-3">
            {!detail && (
              <div className="text-sm text-slate-500 text-center py-8">
                点击左侧任一图片查看：
                <ul className="mt-3 text-left list-disc pl-5 space-y-1">
                  <li>人脸检测框、关键点、质量分</li>
                  <li>1:N 命中人员 (匿名 Person_XXX) 和相似度</li>
                  <li>建议人工复核的决策带</li>
                </ul>
              </div>
            )}
            {detail && (
              <>
                <div className="aspect-[4/3] rounded-lg bg-slate-100 flex items-center justify-center text-slate-400 text-3xl">
                  🚗 车舱照片预览区
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div><span className="label">耗时</span> <span className="font-medium">{detail.processing_ms ?? "—"} ms</span></div>
                  <div><span className="label">状态</span> <span className="font-medium">{detail.processing_status}</span></div>
                  <div><span className="label">检测人脸</span> <span className="font-medium">{detail.detections?.length ?? 0}</span></div>
                  <div><span className="label">候选数</span> <span className="font-medium">{detail.candidate_count}</span></div>
                </div>

                <div>
                  <div className="label mb-1">检测人脸质量</div>
                  <ul className="space-y-1 text-sm">
                    {detail.detections?.map((d, i) => (
                      <li key={d.id} className="flex justify-between bg-slate-50 rounded px-3 py-1.5">
                        <span className="text-slate-600">人脸 #{i + 1}</span>
                        <span>
                          <span className="tag mr-1">Q={(d.quality_score ?? 0).toFixed(2)}</span>
                          <span className="tag mr-1">det={(d.detector_score ?? 0).toFixed(2)}</span>
                          <span className="tag">occ={(d.occlusion_score ?? 0).toFixed(2)}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div>
                  <div className="label mb-1">候选 (Top-K，匿名，需人工复核)</div>
                  <ul className="space-y-2 text-sm">
                    {detail.candidates?.map((c) => (
                      <li key={c.id} className="flex items-center justify-between border border-slate-100 rounded px-3 py-2">
                        <div>
                          <div className="font-medium">{c.external_code}</div>
                          <div className="text-xs text-slate-500">Rank #{c.rank}</div>
                        </div>
                        <div className="text-right">
                          <div className="font-semibold">{(c.similarity * 100).toFixed(1)}%</div>
                          <div className={
                            c.decision_band === "high" ? "band-high" :
                            c.decision_band === "medium" ? "band-medium" :
                            c.decision_band === "low" ? "band-low" : "band-rejected"
                          }>
                            {c.decision_band}
                          </div>
                        </div>
                      </li>
                    ))}
                    {!detail.candidates?.length && <li className="text-xs text-slate-400 text-center py-2">无候选 (被低阈值过滤)</li>}
                  </ul>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
