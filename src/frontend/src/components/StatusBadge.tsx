import React from 'react';

const STATUS_COLORS: Record<string, string> = {
  // Task / Project statuses
  pending: '#9ca3af',
  running: '#ef4444',
  completed: '#22c55e',
  needs_attention: '#eab308',
  abandoned: '#9ca3af',
  draft: '#9ca3af',
  planning: '#3b82f6',
  executing: '#ef4444',
  // Legacy agent statuses
  online: '#22c55e',
  quota_exhausted: '#eab308',
  expired: '#ef4444',
  unknown: '#9ca3af',
  // Four-state agent system (PRD required)
  available: '#22c55e',
  unavailable: '#9ca3af',
  short_reset_pending: '#3b82f6',
  long_reset_pending: '#eab308',
};

const STATUS_LABELS: Record<string, string> = {
  // Task / Project statuses
  pending: '待处理',
  running: '运行中',
  completed: '已完成',
  needs_attention: '需关注',
  abandoned: '已放弃',
  draft: '草稿',
  planning: '规划中',
  executing: '执行中',
  // Legacy agent statuses
  online: '在线',
  quota_exhausted: '额度不足',
  expired: '已过期',
  unknown: '未知',
  // Four-state agent system (PRD required)
  available: '可用',
  unavailable: '不可用',
  short_reset_pending: '待短周期重置',
  long_reset_pending: '待长周期重置',
};

interface Props {
  status: string;
  className?: string;
}

export default function StatusBadge({ status, className }: Props) {
  const color = STATUS_COLORS[status] || '#9ca3af';
  const isAbandoned = status === 'abandoned';
  const label = STATUS_LABELS[status] || status.replace('_', ' ');

  return (
    <span
      className={`status-badge ${className || ''}`}
      style={{
        backgroundColor: `${color}20`,
        color: color,
        border: `1px solid ${color}40`,
        textDecoration: isAbandoned ? 'line-through' : 'none',
      }}
      title={`当前状态：${label}`}
    >
      {label}
    </span>
  );
}
