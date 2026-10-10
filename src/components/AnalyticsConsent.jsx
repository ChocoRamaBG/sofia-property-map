import { useEffect, useId, useState, useSyncExternalStore } from 'react';
import { BarChart3, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import {
  getAnalyticsConsent,
  hasAnalyticsConfiguration,
  initializeAnalytics,
  setAnalyticsConsent,
  subscribeAnalyticsConsent,
} from '@/lib/analytics';

const getServerConsent = () => 'unknown';

export default function AnalyticsConsent({ privacyUrl }) {
  const { pick } = useI18n();
  const headingId = useId();
  const consent = useSyncExternalStore(subscribeAnalyticsConsent, getAnalyticsConsent, getServerConsent);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const configured = hasAnalyticsConfiguration();

  useEffect(() => {
    initializeAnalytics();
  }, []);

  if (!configured) return null;

  const panelOpen = consent === 'unknown' || settingsOpen;
  const choose = (next) => {
    setAnalyticsConsent(next);
    setSettingsOpen(false);
    setAnnouncement(next === 'granted'
      ? pick('Аналитиката е разрешена.', 'Analytics is enabled.')
      : pick('Аналитиката е изключена.', 'Analytics is disabled.'));
  };

  return (
    <div className="analytics-consent">
      <span className="sr-only" role="status" aria-live="polite">{announcement}</span>
      {panelOpen ? (
        <section className="analytics-consent__panel" aria-labelledby={headingId}>
          <div className="analytics-consent__heading">
            <BarChart3 size={18} aria-hidden="true" />
            <h2 id={headingId}>{pick('Аналитика по ваш избор', 'Optional analytics')}</h2>
            {consent !== 'unknown' && (
              <button
                type="button"
                className="analytics-consent__close"
                onClick={() => setSettingsOpen(false)}
                aria-label={pick('Затвори настройките за аналитика', 'Close analytics settings')}
              >
                <X size={18} aria-hidden="true" />
              </button>
            )}
          </div>
          <p className="analytics-consent__description">
            {pick(
              'С ваше разрешение Google Analytics използва бисквитки за статистика за посещенията и действията в сайта. Не изпращаме търсенията, избраните имоти или местоположението на картата. Сайтът работи и без аналитика.',
              'With your permission, Google Analytics uses cookies to measure visits and actions on this site. We do not send your searches, selected properties or map location. The site works without analytics.',
            )}
          </p>
          <p className="analytics-consent__description">
            {pick('Можете да промените избора си по всяко време от „Аналитика“.', 'You can change your choice at any time using “Analytics”.')}
          </p>
          {consent !== 'unknown' && (
            <p className="analytics-consent__status">
              {consent === 'granted'
                ? pick('Текущ избор: разрешена аналитика', 'Current choice: analytics allowed')
                : pick('Текущ избор: без аналитика', 'Current choice: no analytics')}
            </p>
          )}
          <div className="analytics-consent__links">
            {privacyUrl && (
              <a href={privacyUrl} target="_blank" rel="noopener noreferrer">
                {pick('Поверителност на сайта', 'Site privacy')}
              </a>
            )}
            <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">
              {pick('Поверителност в Google', 'Google privacy')}
            </a>
          </div>
          <div className="analytics-consent__actions">
            <button
              type="button"
              className="analytics-consent__button analytics-consent__button--decline"
              onClick={() => choose('denied')}
            >
              {pick('Без аналитика', 'No analytics')}
            </button>
            <button
              type="button"
              className="analytics-consent__button analytics-consent__button--allow"
              onClick={() => choose('granted')}
            >
              {pick('Разреши аналитика', 'Allow analytics')}
            </button>
          </div>
        </section>
      ) : (
        <button
          type="button"
          className="analytics-consent__settings"
          onClick={() => setSettingsOpen(true)}
          aria-expanded={false}
          title={pick('Промени избора за аналитика', 'Change analytics choice')}
        >
          <BarChart3 size={14} aria-hidden="true" />
          {pick('Аналитика', 'Analytics')}
        </button>
      )}
    </div>
  );
}
