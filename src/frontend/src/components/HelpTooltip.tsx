interface HelpTooltipProps {
  text: string;
  ariaLabel?: string;
}

export default function HelpTooltip({ text, ariaLabel = '查看说明' }: HelpTooltipProps) {
  return (
    <span className="help-tooltip">
      <span className="help-tooltip-trigger" tabIndex={0} role="img" aria-label={ariaLabel}>
        ?
      </span>
      <span className="help-tooltip-bubble" role="tooltip">
        {text}
      </span>
    </span>
  );
}
