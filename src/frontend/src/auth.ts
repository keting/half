export interface StoredSession {
  token: string;
  username: string;
  role: string;
  status: string;
}

export interface CurrentUser {
  id: number;
  username: string;
  role: string;
  status: string;
}

export function getStoredToken(): string {
  return localStorage.getItem('token') || '';
}

export function getStoredRole(): string {
  return localStorage.getItem('role') || '';
}

export function getStoredUsername(): string {
  return localStorage.getItem('username') || '';
}

export function setStoredSession(session: StoredSession) {
  localStorage.setItem('token', session.token);
  localStorage.setItem('username', session.username);
  localStorage.setItem('role', session.role);
  localStorage.setItem('status', session.status);
}

export function setStoredCurrentUser(user: CurrentUser) {
  localStorage.setItem('username', user.username);
  localStorage.setItem('role', user.role);
  localStorage.setItem('status', user.status);
}

export function clearStoredSession() {
  localStorage.removeItem('token');
  localStorage.removeItem('username');
  localStorage.removeItem('role');
  localStorage.removeItem('status');
}

export function isAdminUser(): boolean {
  return getStoredRole() === 'admin';
}
