import { useId } from 'react';

interface HelpTooltipProps {
  text: string;
  ariaLabel?: string;
}

export default function HelpTooltip({ text, ariaLabel = '查看说明' }: HelpTooltipProps) {
  const tooltipId = useId();

  const stopLabelActivation = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
  };

  return (
    <span className="help-tooltip">
      <button
        type="button"
        className="help-tooltip-trigger"
        aria-label={ariaLabel}
        aria-describedby={tooltipId}
        onMouseDown={stopLabelActivation}
        onClick={stopLabelActivation}
      >
        ?
      </button>
      <span className="help-tooltip-bubble" id={tooltipId} role="tooltip">
        {text}
      </span>
    </span>
  );
}
