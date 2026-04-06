import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import ProjectListPage from './pages/ProjectListPage';
import ProjectNewPage from './pages/ProjectNewPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import PlanPage from './pages/PlanPage';
import TasksPage from './pages/TasksPage';
import SummaryPage from './pages/SummaryPage';
import AgentsPage from './pages/AgentsPage';
import AgentSettingsPage from './pages/AgentSettingsPage';
import ChangeLogPage from './pages/ChangeLogPage';

function RequireAuth({ children }: { children: React.ReactElement }) {
  const token = localStorage.getItem('token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
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
          <Route path="projects/new" element={<ProjectNewPage />} />
          <Route path="projects/:id/edit" element={<ProjectNewPage />} />
          <Route path="projects/:id" element={<ProjectDetailPage />} />
          <Route path="projects/:id/plan" element={<PlanPage />} />
          <Route path="projects/:id/tasks" element={<TasksPage />} />
          <Route path="projects/:id/summary" element={<SummaryPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="agents/settings" element={<AgentSettingsPage />} />
          <Route path="change-log" element={<ChangeLogPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
