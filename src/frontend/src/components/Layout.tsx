import React from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';

export default function Layout() {
  const navigate = useNavigate();

  function handleLogout() {
    localStorage.removeItem('token');
    navigate('/login');
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h2>HALF</h2>
          <span className="sidebar-subtitle">Human-AI Loop Framework</span>
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/projects" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            项目
          </NavLink>
          <NavLink to="/agents" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            智能体
          </NavLink>
        </nav>
        <div className="sidebar-footer">
          <button className="btn btn-ghost" onClick={handleLogout} title="退出当前账号并返回登录页">
            退出登录
          </button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
