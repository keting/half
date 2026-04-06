import React from 'react';

interface Props {
  label: string;
  display: string;
  tooltip?: string;
  color?: string;
  interval?: string;
  showActions?: boolean;
  onReset?: () => void;
  onConfirm?: () => void;
  disabled?: boolean;
}

export default function CountdownChip({
  label, display, tooltip, color, interval, showActions, onReset, onConfirm, disabled,
}: Props) {
  const isEmpty = display === '-';

  return (
    <div className="countdown-chip">
      <span className="countdown-chip-label">{label}</span>
      <div className="countdown-chip-body">
        <span
          className={`countdown-chip-value ${isEmpty ? 'text-muted' : ''}`}
          title={tooltip}
          style={color ? { color, fontWeight: 600 } : undefined}
        >
          {isEmpty ? '--:--' : display}
        </span>
        {interval && <span className="countdown-chip-interval">{interval}</span>}
      </div>
      {showActions && (
        <div className="countdown-chip-actions">
          <button className="btn btn-xs btn-warning" onClick={onReset} disabled={disabled} title={`点击重置${label}剩余时间`}>
            重置
          </button>
          <button className="btn btn-xs btn-outline" onClick={onConfirm} disabled={disabled} title={`下次${label}重置时间无误`}>
            确认
          </button>
        </div>
      )}
    </div>
  );
}
