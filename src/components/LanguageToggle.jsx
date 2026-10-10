import React from 'react';
import { Languages } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { cn } from '@/lib/utils';

export default function LanguageToggle({ className }) {
  const { lang, setLang } = useI18n();
  return (
    <div
      className={cn('inline-flex items-center rounded-md border border-border bg-card p-0.5', className)}
      role="group"
      aria-label="Language"
    >
      <Languages className="ml-1.5 mr-1 h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
      {['bg', 'en'].map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => setLang(code)}
          aria-pressed={lang === code}
          className={cn(
            'px-2 py-1 text-xs font-semibold uppercase tracking-wide rounded transition-colors',
            lang === code ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
          )}
        >
          {code}
        </button>
      ))}
    </div>
  );
}