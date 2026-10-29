import { screen } from "@testing-library/react";
import { App } from "./App";
import { t } from "./i18n";
import { renderWithProviders } from "./test/renderWithProviders";

describe("App", () => {
  it("hiển thị ChatPage placeholder", () => {
    renderWithProviders(<App />);
    expect(screen.getByText(t("chat.placeholder"))).toBeInTheDocument();
  });
});
