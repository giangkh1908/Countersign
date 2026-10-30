import { createContext, useContext, type ReactNode } from "react";
import { HttpAgentStream } from "./http/httpAgentStream";
import { HttpApprovalApi } from "./http/httpApprovalApi";
import { HttpAuthApi } from "./http/httpAuthApi";
import { HttpThreadApi } from "./http/httpThreadApi";
import type { Api } from "./types";

export const httpApi: Api = {
  agent: new HttpAgentStream(),
  approvals: new HttpApprovalApi(),
  threads: new HttpThreadApi(),
  auth: new HttpAuthApi(),
};

const ApiContext = createContext<Api>(httpApi);

export function ApiProvider({ api = httpApi, children }: { api?: Api; children: ReactNode }) {
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  return useContext(ApiContext);
}
