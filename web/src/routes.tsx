import type { RouteObject } from "react-router-dom";
import { ChatPage } from "./features/chat/ChatPage";

export const routes: RouteObject[] = [
  { path: "/", element: <ChatPage /> },
  // TODO: /t/:threadId, /approval, /admin
];
