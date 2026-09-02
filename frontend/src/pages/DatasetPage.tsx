import { useEffect, useRef, useState } from "react";
import {
  Project, Subject, projectLabel,
  listProjects, createProject, deleteProject,
  listSubjects, createSubject, createSubjectsBatch, deleteSubject,
  uploadReference, getPreferredProjectId, notifyProjectChange, rememberProject,
} from "../api";

// 数据集中许可摘要
const DATASET_LEGAL = [
  {
    name: "DrivFace (UCI ML)",
    license: "许可待核验",
    size: "606 张车内驾驶员 / 4人",
    url: "https://archive.ics.uci.edu/ml/datasets/DrivFace",
    status: "已下载",
    tags: ["驾驶员", "单目", "RGB"],
  },
  {
    name: "WIDER FACE (检测)",
    license: "按官方条款",
    size: "约 32,203 张图 / 393,703 个脸",
    url: "https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/",
    status: "已下载标注（图片待补）",
    tags: ["多尺度", "遮挡", "姿态", "训练检测"],
  },
  {
    name: "LFW (验证)",
    license: "CC BY 4.0 镜像",
    size: "13,233 张图 / 5,749 身份",
    url: "http://vis-www.cs.umass.edu/lfw/",
    status: "已下载",
    tags: ["一对一验证", "跨姿态", "通用基线"],
  },
  {
    name: "DriveFace (近红外)",
    license: "受限 - 需申请 (CC BY-NC-ND 4.0)",
    size: "跨境 4 光谱 · 车舱",
    url: "https://visor-udg.github.io/DriveFace/",
    status: "需申请",
    tags: ["NIR", "多光谱"],
  },
  {
    name: "iCarB-Face",
    license: "受限 - 需向 Idiap 申请",
    size: "197 人 · 56 视频序列",
    url: "https://www.idiap.ch/en/dataset/icarb-face",
    status: "需申请",
    tags: ["视频", "大人群"],
  },
];

export default function DatasetPage() {
  // project
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectDesc, setNewProjectDesc] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);

  // subjects
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [loadingSubjects, setLoadingSubjects] = useState(false);
  const [newExternalCode, setNewExternalCode] = useState("Person_013");
  const [newDisplayName, setNewDisplayName] = useState("匿名-驾驶-013");
  const [batchText, setBatchText] = useState("Person_014,匿名-驾驶-014\nPerson_015,匿名-驾驶-015\nPerson_016,匿名-驾驶-016");
  const [actioningSub, setActioningSub] = useState<number | null>(null);

  // reference upload
  const [refFile, setRefFile] = useState<File | null>(null);
  const [refSubject, setRefSubject] = useState<string>("");
  const [uploadingRef, setUploadingRef] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshProjects = () => {
    setLoadingProjects(true);
    listProjects()
      .then((r) => {
      setProjects(r);
        const preferred = getPreferredProjectId(r[0]?.id ?? 1);
        const next = r.find((item) => item.id === preferred)?.id ?? r[0]?.id ?? null;
        setActiveProjectId((prev) => prev && r.some((item) => item.id === prev) ? prev : next);
        rememberProject(next);
        if (next) notifyProjectChange(next);
      })
      .finally(() => setLoadingProjects(false));
  };

  useEffect(refreshProjects, []);

  useEffect(() => {
    const onProjectChange = (event: Event) => {
      const id = Number((event as CustomEvent).detail);
      if (Number.isFinite(id) && id > 0) setActiveProjectId(id);
    };
    window.addEventListener("face-project-change", onProjectChange);
    return () => window.removeEventListener("face-project-change", onProjectChange);
  }, []);

  useEffect(() => {
    if (!activeProjectId) return;
    setLoadingSubjects(true);
    listSubjects(activeProjectId)
      .then((r) => setSubjects(r))
      .catch((e: any) => {
        setSubjects([]);
        alert("读取人员失败：" + (e?.message || String(e)));
      })
      .finally(() => setLoadingSubjects(false));
  }, [activeProjectId]);

  const handleCreateProject = async () => {
    if (!newProjectName.trim()) return;
    setCreatingProject(true);
    try {
      const p = await createProject(newProjectName.trim(), newProjectDesc.trim());
      setProjects(ps => [...ps, p]);
      setActiveProjectId(p.id);
      notifyProjectChange(p.id);
      setNewProjectName(""); setNewProjectDesc("");
    } catch (e: any) {
      alert("创建项目失败：" + (e?.message || String(e)));
    } finally {
      setCreatingProject(false);
    }
  };

  const handleDeleteProject = async (p: Project) => {
    if (!confirm(`确定删除项目“${projectLabel(p)}”吗？\n该项目下的对象、参考照片、识别记录和向量都会被删除。`)) return;
    try {
      await deleteProject(p.id);
      const remaining = projects.filter((item) => item.id !== p.id);
      setProjects(remaining);
      setActiveProjectId(remaining[0]?.id ?? null);
      if (remaining[0]) notifyProjectChange(remaining[0].id);
      alert("项目已删除");
    } catch (e: any) {
      alert("删除项目失败：" + (e?.response?.data?.detail || e?.message || String(e)));
    }
  };

  const handleCreateSubject = async () => {
    if (!activeProjectId || !newExternalCode.trim()) return;
    try {
      const s = await createSubject(activeProjectId, newExternalCode.trim(), newDisplayName.trim() || undefined);
      setSubjects(ss => [...ss, s]);
      setNewExternalCode(""); setNewDisplayName("");
    } catch (e: any) {
      alert("创建人员失败：" + (e?.message || String(e)));
    }
  };

  const handleBatchSubject = async () => {
    if (!activeProjectId) return;
    const items = batchText
      .split(/\r?\n/)
      .map(l => l.trim())
      .filter(Boolean)
      .map((line) => {
        const [c, n] = line.split(/[,，]/).map(s => s.trim());
        return { external_code: c, display_name: n };
      })
      .filter(x => x.external_code);
    if (!items.length) return;
    try {
      const arr = await createSubjectsBatch(activeProjectId, items);
      setSubjects(ss => [...ss, ...arr]);
    } catch (e: any) {
      alert("批量导入人员失败：" + (e?.message || String(e)));
    }
  };

  const handleDeleteSubject = async (s: Subject) => {
    if (!confirm(`删除人员 ${s.external_code} 及其所有参考图？`)) return;
    setActioningSub(s.id);
    try {
      await deleteSubject(s.id);
      setSubjects(ss => ss.filter(x => x.id !== s.id));
    } catch (e: any) {
      alert("删除人员失败：" + (e?.message || String(e)));
    } finally { setActioningSub(null); }
  };

  const handleUploadRef = async () => {
    if (!activeProjectId || !refFile || !refSubject) return;
    setUploadingRef(true);
    try {
      await uploadReference({ project_id: activeProjectId, external_code: refSubject, file: refFile });
      setRefFile(null); if (fileRef.current) fileRef.current.value = "";
      alert("参考图已注册，人脸被提取并入库。");
    } catch (e: any) {
      alert("上传参考图失败：" + (e?.message || String(e)));
    } finally { setUploadingRef(false); }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-800">
        <div className="font-medium">实验页只回答两个问题</div>
        <div className="mt-1 text-indigo-700">数据集页记录“用了哪些公开数据、许可和规模”；模型评测页记录“模型在什么协议下得到什么指标”。日常录入重点对象和上传照片，请回到工作台的前两个步骤。</div>
      </div>
      {/* 数据集许可信息 (read-only) */}
      <div className="card">
        <div className="card-header">
            <span className="card-title">📚 公开数据集台账（只读）</span>
          <span className="tag">按方案所列 · 全部真实源</span>
        </div>
        <div className="card-body overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-slate-500 border-b border-slate-100">
              <tr>
                <th className="text-left py-2">名称</th>
                <th className="text-left py-2">许可</th>
                <th className="text-left py-2">规模</th>
                <th className="text-left py-2">状态</th>
                <th className="text-left py-2">标签</th>
                <th className="text-left py-2">链接</th>
              </tr>
            </thead>
            <tbody>
              {DATASET_LEGAL.map((d) => (
                <tr key={d.name} className="border-b border-slate-50">
                  <td className="py-2 font-medium">{d.name}</td>
                  <td><span className="tag">{d.license}</span></td>
                  <td className="text-slate-600">{d.size}</td>
                  <td>
                    {d.status === "已下载" || d.status.startsWith("已下载")
                      ? <span className="chip bg-emerald-100 text-emerald-700">✅ {d.status}</span>
                      : <span className="chip bg-amber-100 text-amber-700">🔐 {d.status}</span>}
                  </td>
                  <td className="flex flex-wrap gap-1">
                    {d.tags.map(t => <span key={t} className="tag">{t}</span>)}
                  </td>
                  <td className="text-brand-600 underline text-xs">
                    <a href={d.url} target="_blank" rel="noreferrer">官方页 ↗</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-slate-400 mt-3">
            ℹ 系统在用户手动添加受限数据集前，不会加载其内容；所有导入操作都会写入 audit_logs.dataset_import 事件。
          </p>
        </div>
      </div>

      {/* 项目 + 人员 + 参考图 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 项目管理 */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">🗂 实验项目与数据导入</span>
            {loadingProjects && <span className="tag">加载中…</span>}
          </div>
          <div className="card-body space-y-3">
            <div className="space-y-2">
              <input className="input" placeholder="项目名称 例如：深圳车队-福田线" value={newProjectName} onChange={e => setNewProjectName(e.target.value)} />
              <input className="input" placeholder="项目描述 (可选)" value={newProjectDesc} onChange={e => setNewProjectDesc(e.target.value)} />
              <button className="btn-primary w-full justify-center" disabled={creatingProject} onClick={handleCreateProject}>
                {creatingProject ? "创建中…" : "+ 新建项目"}
              </button>
            </div>
            <div className="divide-y divide-slate-100 pt-1">
              {projects.map((p) => (
                <div
                  key={p.id}
                  className={`w-full flex justify-between items-center py-2.5 px-2 rounded-md text-left transition
                    ${activeProjectId === p.id ? "bg-brand-50 text-brand-700 ring-1 ring-brand-100" : "hover:bg-slate-50"}`}
                >
                  <button type="button" onClick={() => { setActiveProjectId(p.id); notifyProjectChange(p.id); }} className="min-w-0 flex-1 text-left font-medium truncate">{projectLabel(p)}</button>
                  <span className="flex items-center gap-2">
                    <span className={`tag ${p.status === "inactive" || p.status === "disabled" ? "bg-slate-100 text-slate-500" : "bg-emerald-50 text-emerald-700"}`}>
                      {p.status === "inactive" || p.status === "disabled" ? "停用" : "启用"}
                    </span>
                    <button
                      type="button"
                      className="rounded px-1.5 py-0.5 text-xs text-rose-500 hover:bg-rose-50"
                      onClick={() => handleDeleteProject(p)}
                    >删除</button>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 人员管理 */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">👥 实验对象库 {activeProjectId && `(项目 #${activeProjectId})`}</span>
            {loadingSubjects && <span className="tag">加载中…</span>}
          </div>
          <div className="card-body space-y-3 max-h-[680px] overflow-y-auto">
            <div className="grid grid-cols-5 gap-2">
              <input className="col-span-2 input" placeholder="外部编号 (Person_XXX)" value={newExternalCode} onChange={e => setNewExternalCode(e.target.value)} />
              <input className="col-span-2 input" placeholder="显示名 (可选)" value={newDisplayName} onChange={e => setNewDisplayName(e.target.value)} />
              <button className="btn-primary col-span-1 justify-center text-xs !px-2" onClick={handleCreateSubject}>添加</button>
            </div>
            <div>
              <div className="label mb-1">批量导入测试对象（每行：编号,显示名）</div>
              <textarea className="input font-mono text-xs min-h-[84px]" value={batchText} onChange={e => setBatchText(e.target.value)} />
              <div className="flex justify-end mt-2">
                <button className="btn-ghost text-xs" onClick={handleBatchSubject}>批量导入</button>
              </div>
            </div>
            <ul className="divide-y divide-slate-100">
              {subjects.map((s, i) => (
                <li key={s.id} className="py-2 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-slate-400">#{s.id}</span>
                      <span className="font-medium">{s.external_code}</span>
                      {s.authorization_status && s.authorization_status !== "authorized" && <span className="chip bg-slate-100 text-slate-500">{s.authorization_status === "revoked" ? "已撤回" : "停用"}</span>}
                    </div>
                    <div className="text-xs text-slate-500 truncate">
                      {s.display_name || "—"} · 统计请在评测报告查看
                    </div>
                  </div>
                  <button
                    className="btn-ghost text-xs !py-1 !px-2"
                    disabled={actioningSub === s.id}
                    onClick={() => handleDeleteSubject(s)}
                  >
                    删除
                  </button>
                </li>
              ))}
              {!subjects.length && <li className="text-center text-slate-400 text-xs py-6">暂无人员</li>}
            </ul>
          </div>
        </div>

        {/* 参考图上传 */}
        <div className="card">
          <div className="card-header"><span className="card-title">📷 实验参考图注册</span></div>
          <div className="card-body space-y-3">
            <div>
              <div className="label mb-1">关联实验对象编号</div>
              <select className="input" value={refSubject} onChange={(e) => setRefSubject(e.target.value)}>
                <option value="">-- 选一个人员 --</option>
                {subjects.map(s => (
                  <option key={s.id} value={s.external_code}>{s.external_code} {s.display_name && `· ${s.display_name}`}</option>
                ))}
              </select>
            </div>
            <div
              onClick={() => fileRef.current?.click()}
              className="border-2 border-dashed border-slate-300 rounded-lg p-6 text-center text-sm text-slate-500 hover:border-brand-500 hover:bg-brand-50 cursor-pointer"
            >
              {refFile ? (
                <div className="flex items-center justify-center gap-2">
                  <span>✅</span>
                  <span className="font-medium text-slate-700">{refFile.name}</span>
                  <span className="tag">{(refFile.size / 1024).toFixed(0)} KB</span>
                </div>
              ) : (
                <div>
                  <div className="text-lg mb-1">📁 上传参考图（1 张即可，建议多角度补充）</div>
                  <div className="text-xs">系统会检查人脸质量；多人照片会被拒绝，避免污染对象特征</div>
                </div>
              )}
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => setRefFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <button className="btn-primary w-full justify-center" disabled={!refFile || !refSubject || uploadingRef} onClick={handleUploadRef}>
              {uploadingRef ? "上传并提取特征中…" : "📥 注册参考图"}
            </button>
            <div className="text-xs text-slate-400 leading-relaxed">
              注意：参考图库按 project_id 严格隔离，绝不跨项目共享；每人 1 张即可注册，建议补充 3–5 张不同光线/微表情，
              覆盖驾驶姿态但避免严重遮挡。
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
