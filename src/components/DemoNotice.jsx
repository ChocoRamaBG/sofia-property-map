import React from 'react';
import { Info } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
export default function DataNotice() {
  const { t } = useI18n();
  return <div className="data-notice"><Info size={14} aria-hidden="true" /><p>{t('data.notice')}</p></div>;
}
