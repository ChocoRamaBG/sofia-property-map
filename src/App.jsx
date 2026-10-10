import { QueryClientProvider } from '@tanstack/react-query';
import { queryClientInstance } from '@/lib/query-client';
import { LanguageProvider } from '@/lib/i18n';
import { Toaster } from '@/components/ui/toaster';
import Home from '@/pages/Home';
import AnalyticsConsent from '@/components/AnalyticsConsent';

export default function App() {
  return (
    <QueryClientProvider client={queryClientInstance}>
      <LanguageProvider>
        <Home />
        <AnalyticsConsent privacyUrl="/privacy.html" />
        <Toaster />
      </LanguageProvider>
    </QueryClientProvider>
  );
}
