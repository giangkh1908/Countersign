import { useState } from "react";
import { Button } from "../../components/ui/button";
import { Dialog } from "../../components/ui/dialog";
import { t } from "../../i18n";

export function RejectDialog({
  open,
  onOpenChange,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onSubmit: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("approval.reject.title")}>
      <label className="block text-sm">
        {t("approval.reject.reason")}
        <textarea
          className="mt-1 w-full rounded border border-slate-400 p-2"
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          {t("app.cancel")}
        </Button>
        <Button
          variant="danger"
          onClick={() => {
            onSubmit(reason.trim());
            onOpenChange(false);
          }}
        >
          {t("approval.reject.submit")}
        </Button>
      </div>
    </Dialog>
  );
}
