/**
 * Landing-page choreography, loaded on demand (never on the chat route):
 *  - Lenis smooth scroll on the GSAP ticker (one RAF loop), gentle lerp, anchors offset under the header.
 *  - One reveal system: [data-reveal] blocks fade up once; anything already in view stays visible.
 *  - Signature: "How it works" steps drive the sticky preview's stage and a scrubbed progress rule.
 * Returns a disposer that restores the static, fully visible page.
 */

type Gsap = typeof import("gsap").gsap;
type ScrollTriggerType = typeof import("gsap/ScrollTrigger").ScrollTrigger;

const HEADER_OFFSET = -88;
const REVEAL_START = "top 88%";
const STEP_LINE = "60%";

function setupReveals(gsap: Gsap, ScrollTrigger: ScrollTriggerType): void {
  const root = document.documentElement;
  const items = gsap.utils.toArray<HTMLElement>("[data-reveal]");
  const fold = window.innerHeight;
  // Content already on screen is never hidden: the reveal only enhances what is below the fold.
  for (const el of items) if (el.getBoundingClientRect().top < fold) el.dataset.revealed = "";
  root.dataset.reveal = "on";
  ScrollTrigger.batch(
    items.filter((el) => !("revealed" in el.dataset)),
    {
      start: REVEAL_START,
      once: true,
      onEnter: (batch) =>
        batch.forEach((el, i) => {
          (el as HTMLElement).style.setProperty("--i", String(i));
          (el as HTMLElement).dataset.revealed = "";
        }),
    },
  );
}

function stageSetter(stageHost: HTMLElement | null, steps: readonly HTMLElement[]) {
  return (stage: number) => {
    if (stageHost) stageHost.dataset.stage = String(stage);
    steps.forEach((step, i) => {
      if (i < stage) step.dataset.active = "";
      else delete step.dataset.active;
    });
  };
}

function setupHowItWorks(gsap: Gsap, ScrollTrigger: ScrollTriggerType): () => void {
  const host = document.querySelector<HTMLElement>("[data-how]");
  if (!host) return () => undefined;
  const steps = gsap.utils.toArray<HTMLElement>(".how-step", host);
  const setStage = stageSetter(host.querySelector<HTMLElement>(".stage-host[data-stage]"), steps);
  steps.forEach((step, i) =>
    ScrollTrigger.create({
      trigger: step,
      start: `top ${STEP_LINE}`,
      onEnter: () => setStage(i + 1),
      onLeaveBack: () => setStage(Math.max(1, i)),
    }),
  );
  const line = window.innerHeight * 0.6;
  setStage(Math.max(1, steps.filter((s) => s.getBoundingClientRect().top < line).length));
  const list = host.querySelector("ol");
  if (list) {
    gsap.fromTo(
      host.querySelector(".how-progress"),
      { scaleY: 0 },
      { scaleY: 1, ease: "none", scrollTrigger: { trigger: list, start: `top ${STEP_LINE}`, end: `bottom ${STEP_LINE}`, scrub: 0.6 } },
    );
  }
  return () => setStage(steps.length);
}

export async function startLandingMotion(): Promise<() => void> {
  const [{ gsap }, { ScrollTrigger }, { default: Lenis }] = await Promise.all([
    import("gsap"),
    import("gsap/ScrollTrigger"),
    import("lenis"),
  ]);
  gsap.registerPlugin(ScrollTrigger);
  const lenis = new Lenis({ lerp: 0.14, autoRaf: false, anchors: { offset: HEADER_OFFSET }, stopInertiaOnNavigate: true });
  lenis.on("scroll", ScrollTrigger.update);
  const tick = (time: number) => lenis.raf(time * 1000);
  gsap.ticker.add(tick);
  gsap.ticker.lagSmoothing(0);

  let resetHow: () => void = () => undefined;
  const ctx = gsap.context(() => {
    setupReveals(gsap, ScrollTrigger);
    resetHow = setupHowItWorks(gsap, ScrollTrigger);
  });

  return () => {
    ctx.revert();
    resetHow();
    gsap.ticker.remove(tick);
    lenis.destroy();
    document.documentElement.removeAttribute("data-reveal");
  };
}
