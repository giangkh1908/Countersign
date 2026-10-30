import { useState } from "react";
import { Button } from "../../components/ui/button";
import { t } from "../../i18n";

export function Composer({
  disabled,
  streaming,
  onSend,
  onStop,
}: {
  disabled: boolean;
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const submit = () => {
    const v = text.trim();
    if (!v || disabled) return;
    onSend(v);
    setText("");
  };
  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <textarea
        aria-label={t("chat.placeholder")}
        placeholder={t("chat.placeholder")}
        className="flex-1 rounded border border-slate-400 p-2"
        maxLength={8000}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            submit();
          }
        }}
      />
      {streaming ? (
        <Button variant="outline" onClick={onStop}>
          {t("chat.stop")}
        </Button>
      ) : (
        <Button type="submit" disabled={disabled || text.trim() === ""}>
          {t("chat.send")}
        </Button>
      )}
    </form>
  );
}
