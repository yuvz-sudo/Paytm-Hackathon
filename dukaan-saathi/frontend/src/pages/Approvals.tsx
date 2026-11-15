import { useT } from "../i18n";
import { useApi } from "../hooks";
import ActionCard from "../components/ActionCard";
import { DeliveryRow, DELIVERY_NOTE } from "../components/Delivery";
import { Card, Empty, Gate, Title } from "../components/ui";

export default function Approvals({ go }: { go?: (t: string) => void }) {
  const t = useT();
  const pending = useApi<any[]>("/actions?status=pending");
  const outbox = useApi<any[]>("/outbox");
  const done = () => { pending.reload(); outbox.reload(); };
  return (
    <div className="grid lg:grid-cols-2 gap-5">
      <div>
        <Title sub={t("Nothing is sent until you approve it")}>{t("Waiting for your approval")}</Title>
        <Gate state={pending}>
          {(list: any[]) => list.length === 0 ? <Card><Empty text={t("You’re all caught up.")} /></Card> : <div className="space-y-3">{list.map((a) => <ActionCard key={a.id} action={a} onDone={done} />)}</div>}
        </Gate>
      </div>
      <div className="space-y-5">
        <Gate state={outbox}>
          {(list: any[]) => {
            const ready = list.filter((o) => o.status === "ready");
            const rest = list.filter((o) => o.status !== "ready");
            return (<>
              <div>
                <Title sub={DELIVERY_NOTE}>{t("Ready to send")}{ready.length ? ` (${ready.length})` : ""}</Title>
                {ready.length === 0 ? <Card><Empty icon="📤" text="Nothing waiting. Approved messages appear here until you send them." /></Card>
                  : <div className="space-y-2">{ready.map((o) => <DeliveryRow key={o.id} d={o} go={go} onChange={() => outbox.reload()} />)}</div>}
              </div>
              <div>
                <Title sub="Messages you sent (or skipped) after approving">{t("Sent")}</Title>
                {rest.length === 0 ? <Card><Empty icon="✉️" text={t("Nothing sent yet.")} /></Card>
                  : <div className="space-y-2">{rest.slice(0, 30).map((o) => <DeliveryRow key={o.id} d={o} go={go} />)}</div>}
              </div>
            </>);
          }}
        </Gate>
      </div>
    </div>
  );
}
