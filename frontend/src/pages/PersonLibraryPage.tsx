import { useEffect, useState, type ChangeEvent } from "react";
import api from "../api";
import { createSubjectsBatch, deleteReference, deleteSubject, getPreferredProjectId, listProjects, mediaUrl, notifyProjectChange, projectLabel, Project, rememberProject, uploadReferenceFolder } from "../api";

interface Subject {
  id: number;
  external_code: string;
  display_name?: string;
  created_at: string;
}

interface RefImage {
  id: number;
  subject_id: number;
  quality_score?: number;
  object_uri: string;
  created_at: string;
}

interface Props {
  projectId: number;
}

export default function PersonLibraryPage({ projectId }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState(getPreferredProjectId(projectId));
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [refs, setRefs] = useState<Record<number, RefImage[]>>({});
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [selectedSubject, setSelectedSubject] = useState<Subject | null>(null);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [batchText, setBatchText] = useState("");
  const [deletingSubjectId, setDeletingSubjectId] = useState<number | null>(null);
  const [folderUploading, setFolderUploading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await api.get(`/api/v1/projects/${activeProjectId}/subjects`);
      setSubjects(data || []);
      // Load reference images for each subject
      const refsMap: Record<number, RefImage[]> = {};
      for (const s of data || []) {
        try {
          const r = await api.get(`/api/v1/subjects/${s.id}/references`);
          refsMap[s.id] = r.data || [];
        } catch {}
      }
      setRefs(refsMap);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    listProjects().then((items) => {
      setProjects(items || []);
      const preferred = getPreferredProjectId(items?.[0]?.id ?? projectId);
      const next = items?.find((item) => item.id === preferred)?.id ?? items?.[0]?.id ?? projectId;
      if (next !== activeProjectId) setActiveProjectId(next);
      rememberProject(next);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const onProjectChange = (event: Event) => {
      const id = Number((event as CustomEvent).detail);
      if (Number.isFinite(id) && id > 0) setActiveProjectId(id);
    };
    window.addEventListener("face-project-change", onProjectChange);
    return () => window.removeEventListener("face-project-change", onProjectChange);
  }, []);

  useEffect(() => {
    setSelectedSubject(null);
    loadData();
  }, [activeProjectId]);

  const createSubject = async () => {
    if (!newCode.trim()) return;
    try {
      await api.post("/api/v1/subjects", {
        project_id: activeProjectId,
        external_code: newCode.trim(),
        display_name: newName.trim() || undefined,
      });
      setNewCode("");
      setNewName("");
      loadData();
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  const importBatch = async () => {
    const items = batchText.split(/\r?\n/).map((line) => {
      const [code, name] = line.split(/[,，]/).map((x) => x.trim());
      return { external_code: code, display_name: name || undefined };
    }).filter((x) => x.external_code);
    if (!items.length) return;
    try { await createSubjectsBatch(activeProjectId, items); setBatchText(""); loadData(); }
    catch (e: any) { setError(e.response?.data?.detail || e.message); }
  };

  const uploadRef = async (file: File) => {
    if (!selectedSubject) return;
    setUploading(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("project_id", String(activeProjectId));
      fd.append("external_code", selectedSubject.external_code);
      fd.append("file", file);
      await api.post("/api/v1/references/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 60000,
      });
      loadData();
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setUploading(false);
    }
  };

  const uploadFolder = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []).filter((file) => file.type.startsWith("image/"));
    // 允许重复选择同一文件夹
    event.target.value = "";
    if (!files.length) return;
    const roots = new Set(files.map((file) => {
      const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || "";
      return relative.split(/[\\/]/).filter(Boolean)[0] || "";
    }));
    const reserved = new Set(["probe", "unknown", "composite_probe", "watchlist_benchmark"]);
    const mistakenRoot = Array.from(roots).find((root) => reserved.has(root));
    if (mistakenRoot) {
      alert(`“${mistakenRoot}” 是测试图片目录，不是参考图库。请在“图片识别”页面上传 probe/unknown，或在这里选择 enrollment 文件夹。`);
      return;
    }
    const folderNames = files.map((file) => {
      const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || "";
      const parts = relative.split(/[\\/]/).filter(Boolean);
      // 取图片所在的最后一级目录：既支持“人员/照片.jpg”，
      // 也支持选择 probe 这种父目录后出现的“probe/PO-001/照片.jpg”。
      const parent = parts.length > 1 ? parts[parts.length - 2] : "";
      return parent || "未命名对象";
    });
    setFolderUploading(true);
    setError("");
    try {
      const result = await uploadReferenceFolder(activeProjectId, files, folderNames);
      const failed = result.failed || 0;
      alert(`文件夹导入完成：成功 ${result.succeeded} 张，失败 ${failed} 张。` + (failed ? "请查看页面提示并补传失败照片。" : ""));
      await loadData();
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || String(e));
    } finally {
      setFolderUploading(false);
    }
  };

  const regenerateEmbeddings = async (subjectId: number) => {
    try {
      await api.post(`/api/v1/subjects/${subjectId}/re-embed`);
      loadData();
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  const removeReference = async (ref: RefImage) => {
    if (!window.confirm("确定删除这张参考照片吗？删除后只影响这一张照片，不会删除人员。")) return;
    try {
      await deleteReference(ref.id);
      await loadData();
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message);
    }
  };

  const removeSubject = async (subject: Subject) => {
    if (!window.confirm(`确定删除 ${subject.external_code} 及其全部参考照片吗？`)) return;
    setDeletingSubjectId(subject.id);
    setError("");
    try {
      await deleteSubject(subject.id);
      setSelectedSubject(null);
      await loadData();
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setDeletingSubjectId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg border border-slate-200 p-4 flex flex-wrap items-center gap-3">
        <div>
          <div className="text-xs text-slate-500">当前工作项目</div>
          <div className="text-sm text-slate-700 mt-0.5">对象库和参考照片都只属于当前项目</div>
        </div>
        <select
          className="border border-slate-300 rounded-md px-3 py-2 text-sm min-w-64"
          value={activeProjectId}
          onChange={(e) => { const id = Number(e.target.value); setActiveProjectId(id); notifyProjectChange(id); }}
        >
          {projects.length === 0 && <option value={activeProjectId}>项目 #{activeProjectId}</option>}
          {projects.map((p) => <option key={p.id} value={p.id}>{projectLabel(p)}（#{p.id}）</option>)}
        </select>
        <a href="/datasets" className="btn-secondary whitespace-nowrap text-xs">管理项目</a>
      </div>
      <div className="bg-indigo-50 border border-indigo-100 rounded-lg p-4 text-sm text-indigo-800">
        <div className="font-medium">这里做什么？</div>
        <div className="mt-1 text-indigo-700">每个对象至少 1 张单人参考照片即可入库；照片越多、角度和光线越丰富，识别越稳。也可以直接选择“按文件夹批量导入”，文件夹名会自动作为对象编号和名称。</div>
      </div>
      {/* 顶部操作 */}
      <div className="bg-white rounded-lg border border-slate-200 p-5">
        <h2 className="text-base font-semibold text-slate-800 mb-3">新增重点关注对象</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs text-slate-500 mb-1">人员编号 *</label>
            <input
              className="border border-slate-300 rounded-md px-3 py-2 text-sm w-48"
              placeholder="例如 PO-001"
              value={newCode}
              onChange={(e) => setNewCode(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">姓名或备注 (可选)</label>
            <input
              className="border border-slate-300 rounded-md px-3 py-2 text-sm w-48"
              placeholder="例如 张三"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </div>
          <button
            onClick={createSubject}
            className="bg-indigo-600 text-white text-sm px-4 py-2 rounded-md hover:bg-indigo-700 disabled:opacity-50"
            disabled={!newCode.trim()}
          >
            + 添加对象
          </button>
        </div>
        {error && <div className="mt-3 text-xs text-rose-600">⚠ {error}</div>}
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-5">
        <h2 className="text-base font-semibold text-slate-800">批量导入人员名单（可选）</h2>
        <p className="text-xs text-slate-500 mt-1">每行一个对象，格式：人员编号,姓名或备注。例如：PO-001,张三</p>
        <div className="flex gap-3 mt-3">
          <textarea className="flex-1 border border-slate-300 rounded-md px-3 py-2 text-sm min-h-[74px]" placeholder="PO-001,张三\nPO-002,李四" value={batchText} onChange={(e) => setBatchText(e.target.value)} />
          <button onClick={importBatch} disabled={!batchText.trim()} className="self-end bg-slate-100 text-slate-700 text-sm px-4 py-2 rounded-md hover:bg-slate-200 disabled:opacity-50">导入名单</button>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-indigo-200 p-5">
        <h2 className="text-base font-semibold text-slate-800">按文件夹批量导入参考照片</h2>
        <p className="text-xs text-slate-500 mt-1">系统按“图片所在的最后一级文件夹”归类：例如选择 probe 后，probe/PO-001/照片.jpg 会自动归到 PO-001。每个对象文件夹放 1 张或多张单人照片即可，不要放多人合照。</p>
        <label className={`inline-flex mt-3 items-center justify-center text-sm px-4 py-2 rounded-md cursor-pointer ${folderUploading ? "bg-slate-200 text-slate-400" : "bg-indigo-600 text-white hover:bg-indigo-700"}`}>
          <input
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            disabled={folderUploading}
            {...({ webkitdirectory: "", directory: "" } as any)}
            onChange={uploadFolder}
          />
          {folderUploading ? "正在批量提取特征…" : "📁 选择对象文件夹"}
        </label>
        <div className="mt-2 text-xs text-slate-400">示例：重点对象库/张三/照片1.jpg、照片2.jpg；重点对象库/李四/照片1.jpg。系统会自动创建“张三”和“李四”两个对象；选择 probe、enrollment 这类父目录时，也会按其下一级对象文件夹归类。</div>
      </div>

      {/* 人员列表 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading && <div className="text-slate-500 text-sm">加载中...</div>}
        {!loading && subjects.length === 0 && (
          <div className="col-span-full text-center py-10 text-slate-400">
            暂无人员，先创建一个吧
          </div>
        )}
        {subjects.map((s) => {
          const myRefs = refs[s.id] || [];
          const isSelected = selectedSubject?.id === s.id;
          return (
            <div
              key={s.id}
              className={`bg-white rounded-lg border p-4 cursor-pointer transition ${
                isSelected ? "border-indigo-500 ring-2 ring-indigo-100" : "border-slate-200 hover:border-slate-300"
              }`}
              onClick={() => setSelectedSubject(s)}
            >
              <div className="flex items-center justify-between mb-3">
                <div>
                  <div className="font-medium text-sm text-slate-800">{s.external_code}</div>
                  {s.display_name && <div className="text-xs text-slate-500">{s.display_name}</div>}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{myRefs.length} 张参考照片</span>
                  <button
                    type="button"
                    className="text-xs px-2 py-1 rounded border border-rose-200 text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                    disabled={deletingSubjectId === s.id}
                    onClick={(e) => { e.stopPropagation(); removeSubject(s); }}
                  >
                    {deletingSubjectId === s.id ? "删除中" : "删除对象"}
                  </button>
                </div>
              </div>

              {/* 参考图预览 */}
              <div className="grid grid-cols-3 gap-1 mb-3">
                {myRefs.slice(0, 6).map((r, i) => (
                  <div key={r.id} className="relative aspect-square bg-slate-100 rounded overflow-hidden group">
                    {r.object_uri.startsWith("file://") || r.object_uri.startsWith("s3://") ? (
                      <img
                        src={mediaUrl(`/api/v1/references/${r.id}/thumb`)}
                        alt={`ref-${i}`}
                        className="w-full h-full object-cover"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-slate-300 text-xs">
                        #{i + 1}
                      </div>
                    )}
                    <button
                      type="button"
                      className="absolute top-1 right-1 w-6 h-6 rounded-full bg-rose-600/90 text-white text-xs opacity-90 hover:opacity-100 transition"
                      title="删除这张参考照片"
                      onClick={(e) => { e.stopPropagation(); removeReference(r); }}
                    >
                      ×
                    </button>
                  </div>
                ))}
                {myRefs.length === 0 && (
                  <div className="col-span-3 aspect-[3/1] bg-slate-50 rounded flex items-center justify-center text-xs text-slate-400">
                    暂无参考照片
                  </div>
                )}
              </div>

              <div className="flex gap-2">
                <label
                  className="flex-1 text-center text-xs px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded cursor-pointer text-slate-700"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files?.[0]) uploadRef(e.target.files[0]);
                    }}
                  />
                  📷 添加参考照片
                </label>
                <button
                  className="text-xs px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded text-slate-700"
                  onClick={(e) => { e.stopPropagation(); regenerateEmbeddings(s.id); }}
                >
                  ↻ 重新提取特征
                </button>
              </div>
              {isSelected && uploading && (
                <div className="mt-2 text-xs text-indigo-600">正在提取人脸特征...</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
