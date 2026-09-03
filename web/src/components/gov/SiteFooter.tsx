/**
 * Site footer — attribution, statutory basis, and the honesty line.
 *
 * The prototype notice is deliberate and permanent: this system displays
 * statutory clocks and compensation figures, and nobody should mistake a
 * hackathon build for the system of record it models.
 */
export default function SiteFooter() {
  return (
    <footer className="no-print mt-8 border-t border-border bg-bg">
      <div className="mx-auto grid max-w-screen-2xl gap-6 px-4 py-6 text-xs text-muted sm:grid-cols-3">
        <div>
          <div className="mb-1.5 font-semibold text-ink">BhuArjan · भू-अर्जन</div>
          <p className="max-w-prose leading-relaxed">
            National Land Acquisition &amp; Management System. An append-only, hash-chained
            record of every stage, every statutory clock and every rupee.
          </p>
        </div>
        <div>
          <div className="mb-1.5 font-semibold text-ink">Statutory basis</div>
          <ul className="space-y-0.5 leading-relaxed">
            <li>RFCTLARR Act, 2013</li>
            <li>Fourth Schedule enactments</li>
            <li>National Highways Act, 1956</li>
          </ul>
        </div>
        <div>
          <div className="mb-1.5 font-semibold text-ink">Accessibility</div>
          <ul className="space-y-0.5 leading-relaxed">
            <li>Conforms to GIGW 3.0 · WCAG 2.1 Level AA</li>
            <li>Bilingual (English · हिन्दी)</li>
            <li>Keyboard navigable throughout</li>
          </ul>
        </div>
      </div>
      <div className="border-t border-border bg-surface">
        <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center justify-between gap-2 px-4 py-2 text-xs text-muted">
          <span>Ministry of Rural Development · Department of Land Resources</span>
          <span className="font-semibold text-accent2">
            Prototype — SIH 26016. Not a system of record.
          </span>
        </div>
      </div>
    </footer>
  )
}
