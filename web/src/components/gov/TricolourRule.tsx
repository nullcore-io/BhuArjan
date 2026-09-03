/** Saffron / white / green hairline across the top of every page. Decorative. */
export default function TricolourRule() {
  return (
    <div className="flex h-[3px] w-full no-print" aria-hidden="true">
      <div className="flex-1 bg-saffron" />
      <div className="flex-1 bg-bg" />
      <div className="flex-1 bg-deepgreen" />
    </div>
  )
}
