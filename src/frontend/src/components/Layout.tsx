import React from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { api, extractApiErrorDetail } from '../api/client';
import { clearStoredSession, getStoredUsername, isAdminUser, setStoredCurrentUser } from '../auth';
import { CurrentUser } from '../types';

// Keep this in sync with backend PASSWORD_PATTERN in src/backend/routers/auth.py.
const PASSWORD_REGEX = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{6,}$/;

interface ChangePasswordModalProps {
  open: boolean;
  onClose: () => void;
}

function ChangePasswordModal({ open, onClose }: ChangePasswordModalProps) {
  const [currentPassword, setCurrentPassword] = React.useState('');
  const [newPassword, setNewPassword] = React.useState('');
  const [confirmPassword, setConfirmPassword] = React.useState('');
  const [error, setError] = React.useState('');
  const [success, setSuccess] = React.useState('');
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!open) {
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setError('');
      setSuccess('');
      setSaving(false);
    }
  }, [open]);

  React.useEffect(() => {
    if (!open) return undefined;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !saving) {
        onClose();
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, open, saving]);

  if (!open) {
    return null;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setSuccess('');

    if (!currentPassword) {
      setError('请输入当前密码');
      return;
    }
    if (!PASSWORD_REGEX.test(newPassword)) {
      setError('新密码必须至少6位，且包含大写字母、小写字母和数字');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致');
      return;
    }

    setSaving(true);
    try {
      const result = await api.put<{ detail: string }>('/api/auth/password', {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setSuccess(result.detail || '密码修改成功');
      window.setTimeout(() => {
        onClose();
      }, 800);
    } catch (err) {
      setError(extractApiErrorDetail(String(err)) || '修改密码失败，请稍后重试');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={() => { if (!saving) onClose(); }}>
      <div
        className="modal change-password-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="change-password-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h4 id="change-password-title" className="change-password-title">修改密码</h4>
        <p className="change-password-subtitle">请输入当前密码，并设置一个符合强度要求的新密码。</p>
        <form className="change-password-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="currentPassword">当前密码</label>
            <input
              id="currentPassword"
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              autoComplete="current-password"
              disabled={saving}
            />
          </div>
          <div className="form-group">
            <label htmlFor="newPassword">新密码</label>
            <input
              id="newPassword"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder="大小写字母 + 数字，至少6位"
              autoComplete="new-password"
              disabled={saving}
            />
          </div>
          <div className="form-group">
            <label htmlFor="confirmNewPassword">确认新密码</label>
            <input
              id="confirmNewPassword"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              autoComplete="new-password"
              disabled={saving}
            />
          </div>
          {error && <div className="error-message change-password-message">{error}</div>}
          {success && <div className="success-message change-password-message">{success}</div>}
          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={saving}>
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? '提交中...' : '确认修改'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function Layout() {
  const navigate = useNavigate();
  const [username, setUsername] = React.useState(() => getStoredUsername());
  const [isAdmin, setIsAdmin] = React.useState(() => isAdminUser());
  const [showChangePassword, setShowChangePassword] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    api.get<CurrentUser>('/api/auth/me')
      .then((user) => {
        if (cancelled) return;
        setStoredCurrentUser(user);
        setUsername(user.username);
        setIsAdmin(user.role === 'admin');
      })
      .catch(() => {
        if (cancelled) return;
        setUsername(getStoredUsername());
        setIsAdmin(isAdminUser());
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleLogout() {
    api.clearCache();
    clearStoredSession();
    navigate('/login');
  }

  return (
    <div className="app-layout">
      <aside className="sidebar" role="banner">
        <div className="sidebar-brand">
          <h2>HALF</h2>
          <span className="sidebar-subtitle">Human-AI Loop Framework</span>
        </div>
        <nav className="sidebar-nav" role="navigation" aria-label="Main navigation">
          <NavLink to="/projects" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            项目
          </NavLink>
          <NavLink to="/agents" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            智能体
          </NavLink>
          {isAdmin && (
            <NavLink to="/admin/users" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              用户管理
            </NavLink>
          )}
        </nav>
        <div className="sidebar-footer">
          {username && <div className="sidebar-welcome">欢迎您，{username}</div>}
          <button
            className="btn btn-secondary sidebar-action-button"
            onClick={() => setShowChangePassword(true)}
            title="修改当前账号的登录密码"
          >
            修改密码
          </button>
          <button className="btn btn-ghost" onClick={handleLogout} title="退出当前账号并返回登录页">
            退出登录
          </button>
        </div>
      </aside>
      <main className="main-content" role="main" aria-label="Page content">
        <Outlet />
      </main>
      <ChangePasswordModal open={showChangePassword} onClose={() => setShowChangePassword(false)} />
    </div>
  );
}
