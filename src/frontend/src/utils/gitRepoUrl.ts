export const GIT_REPO_URL_ERROR =
  'Git 仓库地址必须是仓库根地址或 clone URL，例如 https://github.com/org/repo、https://github.com/org/repo.git、ssh://git@github.com/org/repo.git 或 git@github.com:org/repo.git；不要填写 issues/pull/tree/blob/graphs 等仓库内页面或内网地址。';
export const GIT_REPO_URL_REQUIRED_ERROR = 'Git 仓库地址不能为空。';

const TWO_SEGMENT_GIT_WEB_HOSTS = new Set([
  'github.com',
  'bitbucket.org',
  'codeberg.org',
  'gitee.com',
]);
const SUBGROUP_GIT_WEB_HOSTS = new Set(['gitlab.com']);

const PAGE_PATH_SEGMENTS = new Set([
  'actions',
  'blob',
  'branches',
  'commit',
  'commits',
  'compare',
  'graphs',
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
const LEGACY_IPV4_COMPONENT_PATTERN = /^(?:0[xX][0-9A-Fa-f]+|0[0-7]*|[1-9][0-9]*|0)$/;

function parseIpv4Component(component: string) {
  if (!LEGACY_IPV4_COMPONENT_PATTERN.test(component)) {
    return null;
  }
  const base = component.toLowerCase().startsWith('0x') ? 16 : component.length > 1 && component.startsWith('0') ? 8 : 10;
  const value = parseInt(component, base);
  return Number.isFinite(value) ? value : null;
}

function parseLegacyIpv4(host: string) {
  if (host.includes(':')) {
    return null;
  }
  const parts = host.split('.');
  if (parts.length < 1 || parts.length > 4) {
    return null;
  }
  const values = parts.map(parseIpv4Component);
  if (values.some((value) => value === null)) {
    return null;
  }

  const [first, second, third, fourth] = values as number[];
  if (parts.length === 1) {
    return first <= 0xffffffff ? first : null;
  }
  if (first > 0xff) {
    return null;
  }
  if (parts.length === 2) {
    return second <= 0xffffff ? first * 0x1000000 + second : null;
  }
  if (parts.length === 3) {
    return second <= 0xff && third <= 0xffff ? first * 0x1000000 + second * 0x10000 + third : null;
  }
  return second <= 0xff && third <= 0xff && fourth <= 0xff
    ? first * 0x1000000 + second * 0x10000 + third * 0x100 + fourth
    : null;
}

function parseIpv4MappedIpv6(host: string) {
  if (!host.startsWith('::ffff:')) {
    return null;
  }
  const rest = host.slice('::ffff:'.length);
  const dotted = parseLegacyIpv4(rest);
  if (dotted !== null) {
    return dotted;
  }
  const hextets = /^([0-9a-f]{1,4}):([0-9a-f]{1,4})$/i.exec(rest);
  return hextets ? parseInt(hextets[1], 16) * 0x10000 + parseInt(hextets[2], 16) : null;
}

function isBlockedIpv4(value: number) {
  const first = Math.floor(value / 0x1000000) & 0xff;
  const second = Math.floor(value / 0x10000) & 0xff;
  return (
    first === 0 ||
    first === 10 ||
    first === 127 ||
    first >= 224 ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168)
  );
}

function isPrivateOrLocalHost(hostname: string) {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (!host || host.endsWith('.') || host === 'localhost' || host === 'localhost.localdomain' || host.endsWith('.localhost')) {
    return true;
  }

  const ipv4Mapped = parseIpv4MappedIpv6(host);
  if (ipv4Mapped !== null) {
    return isBlockedIpv4(ipv4Mapped);
  }

  const legacyIpv4 = parseLegacyIpv4(host);
  if (legacyIpv4 !== null) {
    return isBlockedIpv4(legacyIpv4);
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
  if (!segments) {
    return false;
  }

  const repoName = segments[segments.length - 1];
  const host = hostname.toLowerCase();
  if (TWO_SEGMENT_GIT_WEB_HOSTS.has(host)) {
    return segments.length === 2;
  }
  if (SUBGROUP_GIT_WEB_HOSTS.has(host)) {
    return !looksLikeWebPagePath(segments);
  }
  return repoName.endsWith('.git');
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
