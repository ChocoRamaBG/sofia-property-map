import React from 'react';
import { ArrowUpRight, Building2 } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import LanguageToggle from '@/components/LanguageToggle';

export default function AppHeader() {
  const { t } = useI18n();
  return (
    <header className="app-header">
      <a className="app-brand" href="./" aria-label={t('app.title')}>
        <span className="app-brand-icon"><Building2 size={23} aria-hidden="true" /></span>
        <span><span className="app-brand-name">Sofia<span>Permits</span></span><span className="app-brand-caption">{t('app.subtitle')}</span></span>
      </a>
      <div className="app-header-actions">
        <a className="official-register-link" href="https://nag.sofia.bg/RegisterCertificateForExploitationBuildings" target="_blank" rel="noreferrer">{t('app.officialRegister')}<ArrowUpRight size={15} /></a>
        <LanguageToggle />
      </div>
    </header>
  );
}
