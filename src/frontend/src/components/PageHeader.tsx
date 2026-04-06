import React from 'react';

interface Props {
  title: string;
  description?: string;
  children?: React.ReactNode;
}

export default function PageHeader({ title, description, children }: Props) {
  return (
    <div className="page-header">
      <div className="page-header-text">
        <h1>{title}</h1>
        {description && <p className="page-header-desc">{description}</p>}
      </div>
      {children && <div className="header-actions">{children}</div>}
    </div>
  );
}
