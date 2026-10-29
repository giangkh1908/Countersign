import { t } from "../../i18n";

export function ChatPage() {
  return (
    <main>
      <h1>{t("app.title")}</h1>
      <p>{t("chat.placeholder")}</p>
    </main>
  );
}
