import axios from "axios";

const api = axios.create({
  baseURL: "/",
  timeout: 30_000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("face_recog_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export interface AuthUser { id: number; username: string; role: string; exp?: number; }
export const login = (username: string, password: string) =>
  api.post<{ access_token: string; user: AuthUser }>("/api/v1/auth/login", { username, password }).then((r) => {
    localStorage.setItem("face_recog_token", r.data.access_token);
    return r.data.user;
  });
export const getCurrentUser = () => api.get<AuthUser>("/api/v1/auth/me").then((r) => r.data);
export const logout = () => localStorage.removeItem("face_recog_token");
export const mediaUrl = (path: string) => {
  const token = localStorage.getItem("face_recog_token");
  return token ? `${path}${path.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(token)}` : path;
};

// ====== 仪表盘 ======
export interface DashboardData {
  probe_image_count_today: number;
  face_detected_count_today: number;
  candidate_pending_review: number;
  avg_processing_ms_today: number;
  model_version: { tag: string; decision_band: string };
  thresholds: { high: number; medium: number; low: number };
  band_counts: { high: number; medium: number; low: number; rejected: number };
  project_summary: Array<{ project_id: number; project_name: string; subjects: number; references: number; probes_today: number }>;
  recent_probes: Array<{ id: number; project_id: number; created_at: string; processing_status: string; processing_ms: number | null; candidate_count: number }>;
}
export const getDashboard = () =>
  api.get<DashboardData>("/api/v1/dashboard").then((r) => r.data);

// ====== 项目 ======
export interface Project { id: number; name: string; description?: string; purpose?: string; status?: string; created_at: string; is_active?: boolean; }
export const listProjects = () => api.get<Project[]>("/api/v1/projects").then(r => r.data);
/** Keep legacy storage names auditable while showing plain-language labels in the UI. */
export const projectLabel = (project: Pick<Project, "id" | "name">) =>
  project.id === 1 && /DrivFace|驾驶员识别/i.test(project.name) ? "默认演示项目" : project.name;
const PROJECT_CONTEXT_KEY = "face_recog_active_project";
export const getPreferredProjectId = (fallback = 1) => {
  const value = Number(localStorage.getItem(PROJECT_CONTEXT_KEY));
  return Number.isFinite(value) && value > 0 ? value : fallback;
};
export const rememberProject = (id: number | null | undefined) => {
  if (id && id > 0) localStorage.setItem(PROJECT_CONTEXT_KEY, String(id));
};
export const notifyProjectChange = (id: number) => {
  rememberProject(id);
  window.dispatchEvent(new CustomEvent("face-project-change", { detail: id }));
};
export const createProject = (name: string, description: string) => {
  const fd = new FormData();
  fd.append("name", name);
  if (description) fd.append("purpose", description);
  return api.post<Project>("/api/v1/projects", fd).then(r => r.data);
};
export const deleteProject = (id: number) => api.delete(`/api/v1/projects/${id}`).then(r => r.data);

// ====== 人员 / Subject ======
export interface Subject {
  id: number; project_id: number; external_code: string; display_name?: string;
  created_at: string; is_active?: boolean; authorization_status?: string;
}
export const listSubjects = (project_id: number) =>
  api.get<Subject[]>(`/api/v1/projects/${project_id}/subjects`).then(r => r.data);
export const createSubject = (project_id: number, external_code: string, display_name?: string) =>
  api.post<Subject>("/api/v1/subjects", { project_id, external_code, display_name }).then(r => r.data);
export const createSubjectsBatch = (project_id: number, items: Array<{ external_code: string; display_name?: string }>) =>
  api.post<Subject[]>("/api/v1/subjects/batch", { project_id, items }).then(r => r.data);
export const deleteSubject = (id: number) => api.delete(`/api/v1/subjects/${id}`).then(r => r.data);
export const deleteProbe = (id: number) => api.delete(`/api/v1/probes/${id}`).then(r => r.data);

// ====== 参考图上传 ======
export const uploadReference = (payload: {
  project_id: number; external_code: string; file: File; file_ext?: string;
}) => {
  const fd = new FormData();
  fd.append("project_id", String(payload.project_id));
  fd.append("external_code", payload.external_code);
  fd.append("file", payload.file);
  if (payload.file_ext) fd.append("file_ext", payload.file_ext);
  return api.post("/api/v1/references/upload", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then(r => r.data);
};
export const deleteReference = (id: number) =>
  api.delete(`/api/v1/references/${id}`).then(r => r.data);
export const uploadReferenceFolder = (project_id: number, files: File[], folderNames: string[]) => {
  const fd = new FormData();
  fd.append("project_id", String(project_id));
  files.forEach((file, index) => {
    fd.append("files", file, file.name);
    fd.append("folder_names", folderNames[index] || "未命名对象");
  });
  return api.post("/api/v1/references/folder-upload", fd, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 180_000,
  }).then(r => r.data);
};

// ====== Probe ======
export interface ProbeImage {
  id: number; project_id: number; object_key: string; file_size: number | null;
  created_at: string; processing_status: "pending" | "processing" | "processed" | "failed";
  processing_ms: number | null; error_message: string | null;
  processed_at: string | null; candidate_count: number;
}
export interface ProbeDetail extends ProbeImage {
  detections: Array<{ id: number; face_index: number; bbox: number[]; quality_score: number | null; detector_score: number | null; occlusion_score: number | null }>;
  candidates: Candidate[];
  image_preview_url?: string;
}
export const listProbes = (params?: { project_id?: number; status?: string; limit?: number }) =>
  api.get<ProbeImage[]>("/api/v1/probes/list", { params }).then(r => r.data);
export const getProbe = (id: number) =>
  api.get<ProbeDetail>(`/api/v1/probes/${id}`).then(r => r.data);
export interface ProbeDiagnostic {
  probe_face_id: number;
  usable?: boolean;
  quality_score?: number | null;
  best_candidates: Array<{ subject_code: string; subject_id: number; similarity: number; decision_band: DecisionBand }>;
  reason: string;
  threshold_low?: number;
}
export const getProbeDiagnostics = (id: number) =>
  api.get<{ probe_id: number; model_version: string; faces: ProbeDiagnostic[] }>(`/api/v1/probes/${id}/diagnostics`).then(r => r.data);
export const uploadProbe = (payload: { project_id: number; file: File; async?: boolean }) => {
  const fd = new FormData();
  fd.append("project_id", String(payload.project_id));
  fd.append("file", payload.file);
  return api.post(`/api/v1/probes/upload${payload.async ? "?async=1" : ""}`, fd, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then(r => r.data);
};
export const reprocessProbe = (id: number) =>
  api.post(`/api/v1/probes/${id}/reprocess`).then(r => r.data);
export const exportCandidateResults = async (scope: { projectId?: number; probeId?: number }) => {
  const params = new URLSearchParams();
  if (scope.projectId != null) params.set("project_id", String(scope.projectId));
  if (scope.probeId != null) params.set("probe_id", String(scope.probeId));
  const r = await api.get(`/api/v1/export/candidates.csv?${params.toString()}`, { responseType: "blob" });
  const url = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = scope.probeId != null ? `识别结果-图片${scope.probeId}.csv` : scope.projectId != null ? `识别结果-项目${scope.projectId}.csv` : "识别结果-全部项目.csv";
  a.click();
  URL.revokeObjectURL(url);
};

// ====== Candidates / Review ======
export type DecisionBand = "high" | "medium" | "low" | "rejected";
export type ReviewStatus = "pending" | "confirmed" | "excluded" | "uncertain";
export interface Candidate {
  id: number; probe_id: number; subject_id: number; external_code: string;
  similarity: number; decision_band: DecisionBand; rank: number;
  status: ReviewStatus; review_task_id: number | null;
}
export const listCandidates = (params: {
  project_id?: number; probe_id?: number; status?: ReviewStatus; band?: DecisionBand; limit?: number;
}) => api.get<Candidate[]>("/api/v1/candidates", { params }).then(r => r.data);
export const reviewCandidate = (id: number, decision: "confirm" | "exclude" | "uncertain", note?: string) =>
  api.post(`/api/v1/candidates/${id}/review`, { decision, note }).then(r => r.data);

// ====== Evaluation ======
export interface EvalRun {
  id: number; project_id: number; started_at: string; completed_at: string | null;
  status: "running" | "success" | "failed"; name: string;
  metrics_json?: {
    AUC?: number; EER?: number; FNMR_at_FMR001?: number;
    FMR_sampled?: Array<[number, number]>;
    DET_sampled?: Array<[number, number]>;
    latency_p50?: number; latency_p95?: number; latency_p99?: number;
    total_probes?: number; total_pairs?: number;
  };
  summary?: string;
}
export const listEvalRuns = () => api.get<EvalRun[]>("/api/v1/evaluation/runs").then(r => r.data);

export default api;
