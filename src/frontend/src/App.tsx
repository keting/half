import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import ProjectListPage from './pages/ProjectListPage';

// 重页面走 React.lazy 路由级拆包，避免首屏一次加载所有页面与 reactflow 等重依赖。
const ProjectNewPage = lazy(() => import('./pages/ProjectNewPage'));
const ProjectDetailPage = lazy(() => import('./pages/ProjectDetailPage'));
const ProjectSettingsPage = lazy(() => import('./pages/ProjectSettingsPage'));
const PlanPage = lazy(() => import('./pages/PlanPage'));
const TasksPage = lazy(() => import('./pages/TasksPage'));
const SummaryPage = lazy(() => import('./pages/SummaryPage'));
const AgentsPage = lazy(() => import('./pages/AgentsPage'));
const AgentSettingsPage = lazy(() => import('./pages/AgentSettingsPage'));
const UserManagementPage = lazy(() => import('./pages/UserManagementPage'));

function RequireAuth({ children }: { children: React.ReactElement }) {
  const token = localStorage.getItem('token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function PageFallback() {
  return <div className="page-loading">加载中...</div>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/projects" replace />} />
          <Route path="projects" element={<ProjectListPage />} />
          <Route path="projects/new" element={<Suspense fallback={<PageFallback />}><ProjectNewPage /></Suspense>} />
          <Route path="projects/:id/edit" element={<Suspense fallback={<PageFallback />}><ProjectNewPage /></Suspense>} />
          <Route path="projects/:id" element={<Suspense fallback={<PageFallback />}><ProjectDetailPage /></Suspense>} />
          <Route path="projects/:id/plan" element={<Suspense fallback={<PageFallback />}><PlanPage /></Suspense>} />
          <Route path="projects/:id/tasks" element={<Suspense fallback={<PageFallback />}><TasksPage /></Suspense>} />
          <Route path="projects/:id/summary" element={<Suspense fallback={<PageFallback />}><SummaryPage /></Suspense>} />
          <Route path="settings" element={<Suspense fallback={<PageFallback />}><ProjectSettingsPage /></Suspense>} />
          <Route path="agents" element={<Suspense fallback={<PageFallback />}><AgentsPage /></Suspense>} />
          <Route path="agents/settings" element={<Suspense fallback={<PageFallback />}><AgentSettingsPage /></Suspense>} />
          <Route path="admin/users" element={<Suspense fallback={<PageFallback />}><UserManagementPage /></Suspense>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
