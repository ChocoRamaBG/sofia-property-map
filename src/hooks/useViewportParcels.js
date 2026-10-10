import { useQuery } from '@tanstack/react-query';
import { realEstateApi } from '@/api/realEstateApi';

export default function useViewportParcels(bounds, recordType = 'all') {
  const viewKey = bounds
    ? [bounds.north, bounds.south, bounds.east, bounds.west, bounds.zoom]
        .map((value) => Number(value).toFixed(4))
        .join('|')
    : null;
  const query = useQuery({
    queryKey: ['plots', viewKey, recordType],
    enabled: Boolean(bounds),
    staleTime: 30000,
    queryFn: () => realEstateApi.viewport(bounds, recordType),
  });
  return {
    ...query,
    parcels: query.data?.items || [],
    truncated: Boolean(query.data?.truncated),
    total: query.data?.total || 0,
    apiError: query.isError,
  };
}
