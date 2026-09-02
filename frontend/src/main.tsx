import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import App from "./App";
import PersonLibraryPage from "./pages/PersonLibraryPage";
import ImageRecognitionPage from "./pages/ImageRecognitionPage";
import ReviewPage from "./pages/ReviewPage";
import EvaluationPage from "./pages/EvaluationPage";
import DatasetPage from "./pages/DatasetPage";
import HomePage from "./pages/HomePage";
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
import GovernancePage from "./pages/GovernancePage";
import "./index.css";

const PROJECT_ID = 1; // 默认项目 ID，可后续改为动态

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<HomePage />} />
          <Route path="dashboard" element={<Suspense fallback={<div className="card card-body">正在加载数据大屏…</div>}><DashboardPage /></Suspense>} />
          <Route path="datasets" element={<DatasetPage />} />
          <Route path="persons" element={<PersonLibraryPage projectId={PROJECT_ID} />} />
          <Route path="recognize" element={<ImageRecognitionPage projectId={PROJECT_ID} />} />
          <Route path="review" element={<ReviewPage projectId={PROJECT_ID} />} />
          <Route path="evaluation" element={<EvaluationPage projectId={PROJECT_ID} />} />
          <Route path="governance" element={<GovernancePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
