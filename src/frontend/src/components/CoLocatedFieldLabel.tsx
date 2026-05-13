import HelpTooltip from './HelpTooltip';

const CO_LOCATED_HELP_TEXT = '勾选则表示该agent所在的机器与项目部署的机器是同一台';

interface CoLocatedFieldLabelProps {
  label?: string;
}

export default function CoLocatedFieldLabel({ label = '同服务器' }: CoLocatedFieldLabelProps) {
  return (
    <span className="checkbox-field-label">
      <span>{label}</span>
      <HelpTooltip text={CO_LOCATED_HELP_TEXT} ariaLabel={`${label}说明`} />
    </span>
  );
}
