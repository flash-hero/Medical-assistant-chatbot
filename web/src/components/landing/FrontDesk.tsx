import { BuildingsIcon, ClockIcon, UsersIcon } from "@/components/ui/icons";
import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";

const SMALL = [
  { key: "hours", Icon: ClockIcon },
  { key: "departments", Icon: BuildingsIcon },
  { key: "visiting", Icon: UsersIcon },
] as const;

function FormPreview({ t }: { readonly t: (key: string) => string }) {
  const fields = [
    ["name", ""],
    ["department", t("formPreview.departmentValue")],
    ["dates", t("formPreview.datesValue")],
  ] as const;
  return (
    <figure className="grid gap-3">
      {/* inert: a picture of the real form, not a second form on the page. */}
      <div inert className="grid gap-3 rounded-2xl border border-line bg-surface p-5">
        {fields.map(([key, value]) => (
          <div key={key} className="grid gap-1.5">
            <span className="text-sm font-semibold">{t(`formPreview.${key}`)}</span>
            <span className="field-input flex items-center text-ink-2">{value}</span>
          </div>
        ))}
        <span className="btn btn-primary w-fit">{t("formPreview.submit")}</span>
      </div>
      <figcaption className="text-sm text-ink-2">{t("formPreview.label")}</figcaption>
    </figure>
  );
}

/** Asymmetric group: the appointment request (with its real form) leads, three practical topics follow. */
export async function FrontDesk({ locale }: { readonly locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "Landing" });
  return (
    <section aria-labelledby="desk-title" className="mx-auto max-w-6xl px-4 py-20 sm:px-6 lg:py-28">
      <div className="grid max-w-[44rem] gap-3" data-reveal>
        <h2 id="desk-title" className="text-3xl font-bold sm:text-4xl">
          {t("deskTitle")}
        </h2>
        <p className="text-lg text-ink-2">{t("deskBody")}</p>
      </div>
      <div className="mt-12 grid gap-5 lg:grid-cols-[1.25fr_1fr]">
        <article className="grid gap-6 rounded-card bg-surface-2 p-6 sm:p-8" data-reveal>
          <div className="grid gap-2">
            <h3 className="text-xl font-bold">{t("desk.appointment.title")}</h3>
            <p className="max-w-[48ch] text-ink-2">{t("desk.appointment.body")}</p>
          </div>
          <FormPreview t={t} />
        </article>
        <ul className="grid gap-5">
          {SMALL.map(({ key, Icon }) => (
            <li key={key} className="grid grid-cols-[2.75rem_1fr] gap-4 rounded-card border border-line p-6" data-reveal>
              <span className="grid size-11 place-items-center rounded-full bg-brand-soft text-brand-ink">
                <Icon size={22} aria-hidden="true" />
              </span>
              <div className="grid gap-1">
                <h3 className="text-lg font-bold">{t(`desk.${key}.title`)}</h3>
                <p className="text-ink-2">{t(`desk.${key}.body`)}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
