import { useQuery } from '@tanstack/react-query';
import { realEstateApi } from '@/api/realEstateApi';
import { invalidFilterDates, propertyFilterParams } from '@/lib/propertyFilters';

export default function useViewportParcels(bounds, filters = {}) {
  const filterError = invalidFilterDates(filters);
  const viewKey = bounds
    ? [bounds.north, bounds.south, bounds.east, bounds.west, bounds.zoom]
        .map((value) => Number(value).toFixed(4))
        .join('|')
    : null;
  const query = useQuery({
    queryKey: ['plots', viewKey, propertyFilterParams(filters)],
    enabled: Boolean(bounds) && !filterError,
    staleTime: 30000,
    queryFn: () => realEstateApi.viewport(bounds, filters),
  });
  return {
    ...query,
    parcels: filterError ? [] : query.data?.items || [],
    truncated: !filterError && Boolean(query.data?.truncated),
    total: filterError ? 0 : query.data?.total || 0,
    apiError: !filterError && query.isError,
    filterError,
  };
}
