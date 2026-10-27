import React from 'react';
import { BarChart3, Building2, HardHat, Map } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import LanguageToggle from '@/components/LanguageToggle';

export default function AppHeader({ activeWorkspace = 'map', onWorkspaceChange, alertCount = 0 }) {
  const { t, lang } = useI18n();
  return (
    <header className="app-header">
      <a className="app-brand" href="./" aria-label={t('app.title')} onClick={(event) => { if (onWorkspaceChange) { event.preventDefault(); onWorkspaceChange('map'); } }}>
        <span className="app-brand-icon"><Building2 size={23} aria-hidden="true" /></span>
        <span className="app-brand-name">Sofia<span>Permits</span></span>
      </a>
      {onWorkspaceChange && <nav className="workspace-navigation" aria-label={lang === 'bg' ? 'Основна навигация' : 'Main navigation'}>
        <button type="button" aria-current={activeWorkspace === 'map' ? 'page' : undefined} onClick={() => onWorkspaceChange('map')}><Map size={16} aria-hidden="true" />{lang === 'bg' ? 'Карта' : 'Map'}</button>
        <button type="button" aria-label={lang === 'bg' ? 'Строителни документи и активност' : 'Construction documents and activity'} aria-current={activeWorkspace === 'activity' ? 'page' : undefined} onClick={() => onWorkspaceChange('activity')}><HardHat size={16} aria-hidden="true" /><span className="workspace-label-full">{lang === 'bg' ? 'Строителни документи' : 'Construction documents'}</span><span className="workspace-label-short" aria-hidden="true">{lang === 'bg' ? 'Документи' : 'Documents'}</span></button>
        <button type="button" aria-label={lang === 'bg' ? 'Обяви и цени' : 'Offers and prices'} aria-current={activeWorkspace === 'offers' ? 'page' : undefined} onClick={() => onWorkspaceChange('offers')}><BarChart3 size={16} aria-hidden="true" /><span className="workspace-label-full">{lang === 'bg' ? 'Обяви и цени' : 'Offers & prices'}</span><span className="workspace-label-short" aria-hidden="true">{lang === 'bg' ? 'Обяви' : 'Offers'}</span>{alertCount > 0 && <span className="market-nav-badge" aria-label={lang === 'bg' ? `${alertCount} нови съвпадения` : `${alertCount} new matches`}>{alertCount}</span>}</button>
      </nav>}
      <div className="app-header-actions">
        <LanguageToggle />
      </div>
    </header>
  );
}
