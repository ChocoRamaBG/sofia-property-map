import React from 'react';
import { ArrowUpRight, BarChart3, Building2, Map } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import LanguageToggle from '@/components/LanguageToggle';

export default function AppHeader({ activeWorkspace = 'map', onWorkspaceChange, alertCount = 0 }) {
  const { t, lang } = useI18n();
  return (
    <header className="app-header">
      <a className="app-brand" href="./" aria-label={t('app.title')}>
        <span className="app-brand-icon"><Building2 size={23} aria-hidden="true" /></span>
        <span><span className="app-brand-name">Sofia<span>Permits</span></span><span className="app-brand-caption">{t('app.subtitle')}</span></span>
      </a>
      {onWorkspaceChange && <nav className="workspace-navigation" aria-label={lang === 'bg' ? 'Основна навигация' : 'Main navigation'}>
        <button aria-current={activeWorkspace === 'map' ? 'page' : undefined} onClick={() => onWorkspaceChange('map')}><Map size={16} />{lang === 'bg' ? 'Карта' : 'Map'}</button>
        <button aria-current={activeWorkspace === 'offers' ? 'page' : undefined} onClick={() => onWorkspaceChange('offers')}><BarChart3 size={16} />{lang === 'bg' ? 'Оферти и цени' : 'Offers & prices'}{alertCount > 0 && <span className="market-nav-badge" aria-label={lang === 'bg' ? `${alertCount} нови съвпадения` : `${alertCount} new matches`}>{alertCount}</span>}</button>
      </nav>}
      <div className="app-header-actions">
        <a className="official-register-link" href="https://nag.sofia.bg/RegisterCertificateForExploitationBuildings" target="_blank" rel="noreferrer">{t('app.officialRegister')}<ArrowUpRight size={15} /></a>
        <LanguageToggle />
      </div>
    </header>
  );
}
