import React from 'react';
import { AlertCircle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

const VARIANTS = {
  ok: { className: 'bg-emerald-50 text-emerald-800 border-emerald-200', Icon: CheckCircle2 },
  success: { className: 'bg-emerald-50 text-emerald-800 border-emerald-200', Icon: CheckCircle2 },
  partial: { className: 'bg-amber-50 text-amber-800 border-amber-200', Icon: AlertCircle },
  warning: { className: 'bg-amber-50 text-amber-800 border-amber-200', Icon: AlertCircle },
  failed: { className: 'bg-rose-50 text-rose-800 border-rose-200', Icon: XCircle },
  error: { className: 'bg-rose-50 text-rose-800 border-rose-200', Icon: XCircle },
  running: { className: 'bg-sky-50 text-sky-800 border-sky-200', Icon: Info },
  info: { className: 'bg-secondary text-secondary-foreground border-border', Icon: Info },
  muted: { className: 'bg-muted text-muted-foreground border-border', Icon: Info },
};

export default function StatusPill({ variant = 'info', children, className }) {
  const config = VARIANTS[variant] || VARIANTS.info;
  const Icon = config.Icon;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-tight',
        config.className,
        className
      )}
    >
      <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </span>
  );
}