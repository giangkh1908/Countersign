import { HttpResponse, type RequestHandler } from "msw";

export const handlers: RequestHandler[] = [];

export function sseBody(frames: { event: string; data: unknown }[]): string {
  return (
    ": keepalive\n\n" +
    frames.map((f) => `event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`).join("")
  );
}

export function sseResponse(frames: { event: string; data: unknown }[]): Response {
  return new HttpResponse(sseBody(frames), { headers: { "Content-Type": "text/event-stream" } });
}
