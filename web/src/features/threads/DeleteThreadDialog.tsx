import { Button } from "../../components/ui/button";
import { Dialog } from "../../components/ui/dialog";
import { t } from "../../i18n";

export function DeleteThreadDialog({
  open,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("threads.delete.title")}>
      <p className="text-sm">{t("threads.delete.body")}</p>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          {t("app.cancel")}
        </Button>
        <Button
          variant="danger"
          onClick={() => {
            onConfirm();
            onOpenChange(false);
          }}
        >
          {t("threads.delete.confirm")}
        </Button>
      </div>
    </Dialog>
  );
}
