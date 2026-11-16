import { PhoneIcon } from "@phosphor-icons/react/dist/ssr/Phone";
import { telHref, type PhoneContact } from "@/lib/api/hospital";

interface ContactLinkProps {
  readonly contact: Pick<PhoneContact, "label" | "number" | "hours">;
  readonly callLabel: string;
  readonly tone?: "danger" | "brand" | "quiet";
}

const TONES = { danger: "btn-danger", brand: "btn-primary", quiet: "btn-quiet" } as const;

/** Tap-to-call: the number is visible, dialable, and always left-to-right even in Arabic. */
export function ContactLink({ contact, callLabel, tone = "quiet" }: ContactLinkProps) {
  return (
    <a href={telHref(contact.number)} className={`btn ${TONES[tone]} min-h-12 justify-start gap-3 whitespace-normal px-4 text-start`} aria-label={`${callLabel}, ${contact.number}`}>
      <PhoneIcon size={22} weight="fill" aria-hidden="true" className="shrink-0" />
      <span className="grid">
        <span>{contact.label}</span>
        <span className="text-lg font-bold tabular-nums" dir="ltr">
          {contact.number}
        </span>
        {contact.hours ? <span className="text-sm font-normal">{contact.hours}</span> : null}
      </span>
    </a>
  );
}
