import { useQuery } from '@tanstack/react-query';

export default function useBusinessViewport(bounds, query = '', active = false, level = 'all') {
  const viewKey = bounds ? [bounds.north, bounds.south, bounds.east, bounds.west, bounds.zoom].map((value) => Number(value).toFixed(4)).join('|') : null;
  const result = useQuery({
    queryKey: ['business-map', viewKey, query, level],
    enabled: active && Boolean(bounds),
    staleTime: 30000,
    placeholderData: (previous, previousQuery) => previousQuery?.queryKey[2] === query && previousQuery?.queryKey[3] === level ? previous : undefined,
    queryFn: async ({ signal }) => {
      const url = new URL('./business-data.php', window.location.href);
      url.searchParams.set('action', 'viewport');
      url.searchParams.set('level', level);
      Object.entries(bounds).forEach(([key, value]) => url.searchParams.set(key, String(value)));
      if (query) url.searchParams.set('q', query);
      const response = await fetch(url, { signal, headers: { Accept: 'application/json' } });
      const data = await response.json();
      if (!response.ok || data.error || !Array.isArray(data.items)) throw new Error('Company map unavailable');
      return data;
    },
  });
  return { ...result, parcels: result.data?.items || [], total: result.data?.total || 0, companyTotal: result.data?.company_total || 0, isLoading: result.isFetching, apiError: result.isError };
}
