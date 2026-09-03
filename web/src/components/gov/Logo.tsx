/**
 * BhuArjan site mark.
 *
 * The emblem only — cropped from BhuArjan_official_logo.jpg, whose wordmark is
 * deliberately left out: the masthead renders "BhuArjan भू-अर्जन" as live text so
 * it scales with the A-/A/A+ control and is read aloud by a screen reader.
 * Baking the words into the bitmap would give up both.
 *
 * Decorative here — the adjacent text already names the system — so it carries
 * an empty alt and is hidden from assistive tech.
 */
import logo from '../../assets/bhuarjan-logo.png'

export default function Logo({ size = 40, className = '' }: { size?: number; className?: string }) {
  return (
    <img
      src={logo}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      className={className}
      style={{ width: size, height: size }}
    />
  )
}
