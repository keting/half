import React from 'react';

interface Props {
  type?: string;
  model?: string | null;
}

export default function ModelBadge({ type, model }: Props) {
  return (
    <span className="model-badge-group">
      {type && <span className="badge badge-type">{type}</span>}
      {model && <span className="badge badge-model">{model}</span>}
    </span>
  );
}
