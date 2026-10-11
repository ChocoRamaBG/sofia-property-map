import { useQuery } from '@tanstack/react-query';
import { realEstateApi } from '@/api/realEstateApi';
import { invalidFilterArea, invalidFilterDates, propertyFilterParams } from '@/lib/propertyFilters';

export default function useViewportParcels(bounds, filters = {}) {
  const filterError = invalidFilterDates(filters) ? 'filter.dateRangeError' : invalidFilterArea(filters) ? 'filter.areaRangeError' : null;
  const filterParams = propertyFilterParams(filters);
  const viewKey = bounds
    ? [bounds.north, bounds.south, bounds.east, bounds.west, bounds.zoom]
        .map((value) => Number(value).toFixed(4))
        .join('|')
    : null;
  const query = useQuery({
    queryKey: ['plots', viewKey, filterParams],
    enabled: Boolean(bounds) && !filterError,
    staleTime: 30000,
    queryFn: ({ signal }) => realEstateApi.viewport(bounds, filters, signal),
    placeholderData: (previous, previousQuery) => JSON.stringify(previousQuery?.queryKey[2]) === JSON.stringify(filterParams) ? previous : undefined,
  });
  return {
    ...query,
    isLoading: !filterError && query.isFetching,
    parcels: filterError ? [] : query.data?.items || [],
    truncated: !filterError && Boolean(query.data?.truncated),
    total: filterError ? 0 : query.data?.total || 0,
    apiError: !filterError && query.isError,
    filterError,
  };
}
