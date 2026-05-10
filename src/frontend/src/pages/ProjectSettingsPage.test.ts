import { describe, expect, it, vi } from 'vitest';

import {
  loadProjectSettingsData,
  saveProjectSettingsData,
  toggleFeishuNotifyEvent,
} from './ProjectSettingsPage';

describe('ProjectSettingsPage Feishu helpers', () => {
  it('loads only personal Feishu settings for non-admin users', async () => {
    const getCalls: string[] = [];
    const result = await loadProjectSettingsData(false, {
      get: async <T,>(path: string) => {
        getCalls.push(path);
        if (path === '/api/settings/feishu') {
          return {
            webhook_url: 'https://open.feishu.cn/open-apis/bot/v2/hook/user-token',
            notify_events: ['completed'],
          } as T;
        }
        throw new Error(`unexpected path: ${path}`);
      },
      put: async <T,>() => undefined as T,
    });

    expect(getCalls).toEqual(['/api/settings/feishu']);
    expect(result).toEqual({
      settings: null,
      promptSettings: null,
      feishuSettings: {
        webhook_url: 'https://open.feishu.cn/open-apis/bot/v2/hook/user-token',
        notify_events: ['completed'],
      },
    });
  });

  it('saves admin settings and returns backend-updated prompt plus Feishu payloads', async () => {
    const putCalls: string[] = [];

    const result = await saveProjectSettingsData(
      true,
      { webhook_url: 'https://open.feishu.cn/open-apis/bot/v2/hook/admin-token', notify_events: ['timeout'] },
      {
        get: async <T,>() => undefined as T,
        put: async <T,>(path: string, body?: unknown) => {
          putCalls.push(path);
          if (path === '/api/settings/polling') {
            return { message: 'ok' } as T;
          }
          if (path === '/api/settings/prompt') {
            expect(body).toEqual({ co_location_guidance: 'guide me' });
            return { co_location_guidance: 'guide me', default_co_location_guidance: 'default guide' } as T;
          }
          if (path === '/api/settings/feishu') {
            return body as T;
          }
          throw new Error(`unexpected path: ${path}`);
        },
      },
      {
        polling_interval_min: 15,
        polling_interval_max: 30,
        polling_start_delay_minutes: 0,
        polling_start_delay_seconds: 0,
        task_timeout_minutes: 10,
      },
      {
        co_location_guidance: 'guide me',
        default_co_location_guidance: 'default guide',
      }
    );

    expect(putCalls).toEqual([
      '/api/settings/polling',
      '/api/settings/prompt',
      '/api/settings/feishu',
    ]);
    expect(result).toEqual({
      promptSettings: {
        co_location_guidance: 'guide me',
        default_co_location_guidance: 'default guide',
      },
      feishuSettings: {
        webhook_url: 'https://open.feishu.cn/open-apis/bot/v2/hook/admin-token',
        notify_events: ['timeout'],
      },
    });
  });

  it('toggles Feishu event selections without duplicates', () => {
    expect(toggleFeishuNotifyEvent(['completed'], 'timeout', true)).toEqual(['completed', 'timeout']);
    expect(toggleFeishuNotifyEvent(['completed'], 'completed', true)).toEqual(['completed']);
    expect(toggleFeishuNotifyEvent(['completed', 'timeout'], 'completed', false)).toEqual(['timeout']);
  });
});