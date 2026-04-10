import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, extractApiErrorDetail } from '../api/client';
import { isAdminUser } from '../auth';
import PageHeader from '../components/PageHeader';
import { AdminUser, CurrentUser } from '../types';

function formatDateTime(value: string | null) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN');
}

function roleLabel(role: string) {
  return role === 'admin' ? '管理员' : '普通用户';
}

function statusLabel(status: string) {
  return status === 'active' ? '正常' : '冻结中';
}

export default function UserManagementPage() {
  const navigate = useNavigate();
  const isAdmin = isAdminUser();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [savingAction, setSavingAction] = useState('');

  useEffect(() => {
    if (!isAdmin) {
      navigate('/projects', { replace: true });
      return;
    }
    fetchUsers();
  }, [isAdmin, navigate]);

  function fetchUsers() {
    setLoading(true);
    setError('');
    Promise.all([
      api.get<CurrentUser>('/api/auth/me'),
      api.get<AdminUser[]>('/api/admin/users'),
    ])
      .then(([me, list]) => {
        setCurrentUser(me);
        setUsers(list);
      })
      .catch((err) => setError(extractApiErrorDetail(String(err)) || '加载用户列表失败'))
      .finally(() => setLoading(false));
  }

  async function updateRole(user: AdminUser, role: 'admin' | 'user') {
    const targetLabel = role === 'admin' ? '管理员' : '普通用户';
    if (!window.confirm(`确定要将用户 ${user.username} 设为${targetLabel}吗？`)) {
      return;
    }
    setSavingAction(`role-${user.id}`);
    setError('');
    try {
      const updated = await api.put<AdminUser>(`/api/admin/users/${user.id}/role`, { role });
      setUsers((prev) => prev.map((item) => item.id === updated.id ? updated : item));
    } catch (err) {
      setError(extractApiErrorDetail(String(err)) || '更新用户角色失败');
    } finally {
      setSavingAction('');
    }
  }

  async function updateStatus(user: AdminUser, status: 'active' | 'frozen') {
    if (status === 'frozen' && !window.confirm(`确定要冻结用户 ${user.username} 吗？冻结后该用户将无法登录。`)) {
      return;
    }
    setSavingAction(`status-${user.id}`);
    setError('');
    try {
      const updated = await api.put<AdminUser>(`/api/admin/users/${user.id}/status`, { status });
      setUsers((prev) => prev.map((item) => item.id === updated.id ? updated : item));
    } catch (err) {
      setError(extractApiErrorDetail(String(err)) || '更新用户状态失败');
    } finally {
      setSavingAction('');
    }
  }

  if (loading) {
    return <div className="page-loading">正在加载用户列表...</div>;
  }

  return (
    <div className="page">
      <PageHeader title="用户管理" description="查看当前系统中的用户，并管理角色与账号状态" />

      {error && <div className="error-message">{error}</div>}

      <div className="table-scroll">
        <table className="data-table user-table">
          <thead>
            <tr>
              <th>用户名</th>
              <th>注册时间</th>
              <th>最后登录时间</th>
              <th>最后登录 IP</th>
              <th>用户类型</th>
              <th>用户状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 ? (
              <tr>
                <td className="empty-row" colSpan={7}>当前没有用户数据</td>
              </tr>
            ) : users.map((user) => {
              const roleBusy = savingAction === `role-${user.id}`;
              const statusBusy = savingAction === `status-${user.id}`;
              const nextRole = user.role === 'admin' ? 'user' : 'admin';
              const nextStatus = user.status === 'active' ? 'frozen' : 'active';
              const isSelf = currentUser?.id === user.id;
              const activeAdminCount = users.filter((item) => item.role === 'admin' && item.status === 'active').length;
              const isLastActiveAdmin = user.role === 'admin' && user.status === 'active' && activeAdminCount <= 1;
              const disableRoleAction = roleBusy || statusBusy || isSelf || (user.role === 'admin' && isLastActiveAdmin);
              const disableStatusAction = roleBusy || statusBusy || (nextStatus === 'frozen' && (isSelf || isLastActiveAdmin));
              const roleTitle = isSelf
                ? '不能修改自己的角色'
                : (user.role === 'admin' && isLastActiveAdmin ? '系统至少需要保留一个激活状态的管理员' : undefined);
              const statusTitle = isSelf && nextStatus === 'frozen'
                ? '不能冻结自己'
                : (nextStatus === 'frozen' && isLastActiveAdmin ? '系统至少需要保留一个激活状态的管理员' : undefined);

              return (
                <tr key={user.id}>
                  <td className="user-name-cell">{user.username}</td>
                  <td>{formatDateTime(user.created_at)}</td>
                  <td>{formatDateTime(user.last_login_at)}</td>
                  <td>{user.last_login_ip || '-'}</td>
                  <td>
                    <span className={`user-pill ${user.role === 'admin' ? 'user-pill-admin' : ''}`}>
                      {roleLabel(user.role)}
                    </span>
                  </td>
                  <td>
                    <span className={`user-pill ${user.status === 'frozen' ? 'user-pill-frozen' : 'user-pill-active'}`}>
                      {statusLabel(user.status)}
                    </span>
                  </td>
                  <td>
                    <div className="user-actions">
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => updateRole(user, nextRole)}
                        disabled={disableRoleAction}
                        title={roleTitle}
                      >
                        {roleBusy ? '处理中...' : (user.role === 'admin' ? '设为普通用户' : '设为管理员')}
                      </button>
                      <button
                        className={`btn btn-sm ${user.status === 'active' ? 'btn-danger' : 'btn-primary'}`}
                        onClick={() => updateStatus(user, nextStatus)}
                        disabled={disableStatusAction}
                        title={statusTitle}
                      >
                        {statusBusy ? '处理中...' : (user.status === 'active' ? '冻结' : '解冻')}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
