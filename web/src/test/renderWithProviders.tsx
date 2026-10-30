import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { ApiProvider } from "../api/ApiProvider";
import { FakeAgentStream } from "../api/fakes/FakeAgentStream";
import { FakeApprovalApi } from "../api/fakes/FakeApprovalApi";
import { FakeAuthApi, FakeThreadApi } from "../api/fakes/FakeThreadApi";
import type { Api } from "../api/types";

export function fakeApi(over: Partial<Api> = {}): Api {
  return {
    agent: new FakeAgentStream(),
    approvals: new FakeApprovalApi({
      interrupt_id: "i",
      intent_id: "n",
      op: "close_ticket",
      title: "t",
      risk: "low",
      risk_flags: [],
      expires_at: "2099-01-01T00:00:00Z",
      server_time: "2098-12-31T23:59:00Z",
      intent_sha256: "a".repeat(64),
      display_fields: [],
    }),
    threads: new FakeThreadApi(),
    auth: new FakeAuthApi(),
    ...over,
  };
}

export function renderWithProviders(ui: ReactElement, opts: { route?: string; api?: Api } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ApiProvider api={opts.api ?? fakeApi()}>
        <MemoryRouter initialEntries={[opts.route ?? "/"]}>{ui}</MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  );
}
