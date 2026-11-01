import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "../../api/ApiProvider";

export function useThreads() {
  const { threads } = useApi();
  return useInfiniteQuery({
    queryKey: ["threads"],
    queryFn: ({ pageParam }) => threads.list({ limit: 20, before: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_before ?? undefined,
  });
}

export function useDeleteThread() {
  const { threads } = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => threads.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["threads"] }),
  });
}
