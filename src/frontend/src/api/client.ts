const BASE_URL = '';

interface RequestOptions extends RequestInit {
  signal?: AbortSignal;
}

export function extractApiErrorDetail(message: string): string | null {
  const match = message.match(/^(?:Error:\s+)?API error \d+:\s*(.*)$/s);
  if (!match) {
    return null;
  }

  const rawBody = match[1]?.trim();
  if (!rawBody) {
    return null;
  }

  try {
    const parsed = JSON.parse(rawBody);
    if (typeof parsed?.detail === 'string' && parsed.detail.trim()) {
      return parsed.detail.trim();
    }
  } catch {
    // Ignore JSON parse failures and fall back to raw text.
  }

  return rawBody;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API error ${res.status}: ${body}`);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json();
}

// ---- 简易 stale-while-revalidate 缓存 ----
// 用于跨页面共享低频变化的 GET 接口（如 /api/agents、/api/projects/:id），
// 避免每次切页都白屏等待网络。
//
// 行为：
//   - 命中缓存：立刻同步返回旧值（通过 onData 回调），同时在后台静默重新请求一次；
//     新数据回来后再次触发 onData。
//   - 未命中：发起请求，写入缓存。
//   - 同一 path 已有 in-flight 请求：复用，不重复发起。
//
// 这是一个最小实现，故意不做 LRU/过期清理；条目数量级很小。

interface CacheEntry<T> {
  value?: T;
  inFlight?: Promise<T>;
}

const cache = new Map<string, CacheEntry<unknown>>();

function getCached<T>(
  path: string,
  onData: (value: T, fromCache: boolean) => void,
): Promise<T> {
  const entry = (cache.get(path) as CacheEntry<T> | undefined) ?? {};

  if (entry.value !== undefined) {
    // 立刻把缓存值丢出去
    try { onData(entry.value, true); } catch { /* ignore */ }
  }

  if (entry.inFlight) {
    return entry.inFlight;
  }

  const p = request<T>(path)
    .then((value) => {
      cache.set(path, { value });
      try { onData(value, false); } catch { /* ignore */ }
      return value;
    })
    .catch((err) => {
      // 失败时清掉 inFlight，但保留旧 value，便于下次重试
      const cur = (cache.get(path) as CacheEntry<T> | undefined) ?? {};
      cache.set(path, { value: cur.value });
      // 若已经有旧值，则把这次后台刷新视为“静默失败”，直接回退到旧值，
      // 避免页面侧 `void api.getCached(...)` 产生未处理 Promise 拒绝。
      if (cur.value !== undefined) {
        return cur.value;
      }
      throw err;
    });

  cache.set(path, { value: entry.value, inFlight: p });
  return p;
}

function invalidate(path: string) {
  cache.delete(path);
}

function invalidatePrefix(prefix: string) {
  for (const key of Array.from(cache.keys())) {
    if (key.startsWith(prefix)) cache.delete(key);
  }
}

function clearCache() {
  cache.clear();
}

export const api = {
  get<T>(path: string, options?: RequestOptions) {
    return request<T>(path, options);
  },
  post<T>(path: string, body?: unknown) {
    return request<T>(path, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  put<T>(path: string, body?: unknown) {
    return request<T>(path, {
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  patch<T>(path: string, body?: unknown) {
    return request<T>(path, {
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  delete<T>(path: string) {
    return request<T>(path, { method: 'DELETE' });
  },
  // stale-while-revalidate GET
  getCached,
  invalidate,
  invalidatePrefix,
  clearCache,
};
