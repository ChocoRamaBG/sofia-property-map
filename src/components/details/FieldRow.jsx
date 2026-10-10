import React from 'react';
import { MinusCircle } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { cn } from '@/lib/utils';

/**
 * One labelled value. When the value is absent it is explicitly shown as
 * missing in the source — never hidden and never guessed.
 */
export default function FieldRow({ label, value, hint, className }) {
  const { t } = useI18n();
  const missing = value === undefined || value === null || value === '';
  return (
    <div className={cn('grid grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] gap-2 py-1.5', className)}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-xs">
        {missing ? (
          <span className="inline-flex items-start gap-1 text-muted-foreground/90 italic">
            <MinusCircle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
            <span>{t('value.notAvailable')}</span>
          </span>
        ) : (
          <span className="font-medium break-words">{value}</span>
        )}
        {hint ? <span className="mt-0.5 block text-[11px] text-muted-foreground">{hint}</span> : null}
      </dd>
    </div>
  );
}