export const GIT_REPO_URL_ERROR =
  'Git 仓库地址必须是仓库根地址或 clone URL，例如 https://github.com/org/repo、https://github.com/org/repo.git、ssh://git@github.com/org/repo.git 或 git@github.com:org/repo.git；不要填写 issues/pull/tree/blob 页面或内网地址。';
export const GIT_REPO_URL_REQUIRED_ERROR = 'Git 仓库地址不能为空。';

const KNOWN_GIT_WEB_HOSTS = new Set([
  'github.com',
  'gitlab.com',
  'bitbucket.org',
  'codeberg.org',
  'gitee.com',
]);

const PAGE_PATH_SEGMENTS = new Set([
  'actions',
  'blob',
  'branches',
  'commit',
  'commits',
  'compare',
  'issues',
  'merge_requests',
  'network',
  'pull',
  'pulls',
  'releases',
  'security',
  'settings',
  'tree',
  'wiki',
]);

const PATH_SEGMENT_PATTERN = /^[A-Za-z0-9._~+-]+$/;
const SSH_USERNAME_PATTERN = /^[A-Za-z0-9._][A-Za-z0-9._-]*$/;
const HOSTNAME_PATTERN = /^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$/;

function isPrivateOrLocalHost(hostname: string) {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (!host || host.endsWith('.') || host === 'localhost' || host === 'localhost.localdomain' || host.endsWith('.localhost')) {
    return true;
  }

  if (
    /^127\./.test(host) ||
    /^10\./.test(host) ||
    /^192\.168\./.test(host) ||
    /^169\.254\./.test(host) ||
    /^172\.(1[6-9]|2\d|3[0-1])\./.test(host) ||
    host === '0.0.0.0'
  ) {
    return true;
  }

  if (!host.includes(':')) {
    return false;
  }

  return host === '::1' || host.startsWith('fe80:') || host.startsWith('fc') || host.startsWith('fd');
}

function isValidHostname(hostname: string) {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (host.includes(':')) {
    return true;
  }
  return HOSTNAME_PATTERN.test(host);
}

function pathSegments(pathname: string) {
  const normalized = pathname.replace(/^\/+|\/+$/g, '');
  if (!normalized || normalized.startsWith('-') || normalized.includes('\\')) {
    return null;
  }

  const segments = normalized.split('/').map((segment) => {
    try {
      return decodeURIComponent(segment);
    } catch {
      return '';
    }
  });

  if (segments.length < 2) {
    return null;
  }

  return segments.every((segment) => segment && segment !== '.' && segment !== '..' && !segment.startsWith('-') && PATH_SEGMENT_PATTERN.test(segment))
    ? segments
    : null;
}

function looksLikeWebPagePath(segments: string[]) {
  return segments.slice(2).some((segment) => PAGE_PATH_SEGMENTS.has(segment));
}

function isValidRepoPath(hostname: string, pathname: string) {
  const segments = pathSegments(pathname);
  if (!segments || looksLikeWebPagePath(segments)) {
    return false;
  }

  const repoName = segments[segments.length - 1];
  return repoName.endsWith('.git') || KNOWN_GIT_WEB_HOSTS.has(hostname.toLowerCase());
}

export function validateGitRepoUrl(value: string | null | undefined, options: { required?: boolean } = {}) {
  const trimmed = (value || '').trim();
  if (!trimmed) {
    return options.required ? GIT_REPO_URL_REQUIRED_ERROR : null;
  }

  if (trimmed.startsWith('-') || trimmed.toLowerCase().startsWith('ext::')) {
    return GIT_REPO_URL_ERROR;
  }

  const scpMatch = /^git@([^:/\s]+):([^\s]+)$/i.exec(trimmed);
  if (scpMatch) {
    const host = scpMatch[1].toLowerCase();
    return !isPrivateOrLocalHost(host) && isValidHostname(host) && isValidRepoPath(host, scpMatch[2])
      ? null
      : GIT_REPO_URL_ERROR;
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return GIT_REPO_URL_ERROR;
  }

  if (parsed.protocol !== 'https:' && parsed.protocol !== 'ssh:') {
    return GIT_REPO_URL_ERROR;
  }

  const host = parsed.hostname.toLowerCase();
  if (!isValidHostname(host) || isPrivateOrLocalHost(host) || parsed.search || parsed.hash || parsed.password) {
    return GIT_REPO_URL_ERROR;
  }

  if (parsed.protocol === 'https:' && parsed.username) {
    return GIT_REPO_URL_ERROR;
  }

  if (parsed.protocol === 'ssh:' && !SSH_USERNAME_PATTERN.test(parsed.username)) {
    return GIT_REPO_URL_ERROR;
  }

  return isValidRepoPath(host, parsed.pathname) ? null : GIT_REPO_URL_ERROR;
}
