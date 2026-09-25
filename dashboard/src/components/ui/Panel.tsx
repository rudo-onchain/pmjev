import React from 'react';

interface PanelProps extends React.HTMLAttributes<HTMLElement> {
  as?: 'section' | 'div' | 'aside';
}

export function Panel({ as: Tag = 'section', className = '', children, ...rest }: PanelProps) {
  return (
    <Tag
      className={`rounded-2xl border border-line bg-surface shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)] ${className}`}
      {...rest}>
      
      {children}
    </Tag>);

}