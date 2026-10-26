import React, { Suspense } from 'react';
import { RefreshCw } from 'lucide-react';
import { useI18n } from '@/lib/i18n';

class PanelBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.errorFallback : this.props.children; }
}

export default function AsyncPanel({ children, fallback }) {
  const { pick } = useI18n();
  return <PanelBoundary errorFallback={<div className="workspace-load-error" role="alert">
    <strong>{pick('Разделът не успя да се зареди.', 'This section could not load.')}</strong>
    <p>{pick('Обновете страницата, за да опитате отново.', 'Refresh the page to try again.')}</p>
    <button type="button" onClick={() => window.location.reload()}><RefreshCw size={16} aria-hidden="true" />{pick('Обнови страницата', 'Refresh page')}</button>
  </div>}><Suspense fallback={fallback}>{children}</Suspense></PanelBoundary>;
}
