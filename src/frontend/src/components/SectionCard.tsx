import React from 'react';

interface Props {
  title?: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}

export default function SectionCard({ title, description, children, className }: Props) {
  return (
    <div className={`section-card ${className || ''}`}>
      {title && (
        <div className="section-card-header">
          <h3 className="section-card-title">{title}</h3>
          {description && <p className="section-card-desc">{description}</p>}
        </div>
      )}
      <div className="section-card-body">{children}</div>
    </div>
  );
}
