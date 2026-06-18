// mova.io brand mark. Faithful recreation (rounded wordmark + gradient-outline "io"
// box + ™). To use the official asset instead, drop it at public/mova-logo.svg and
// swap the markup below for: <img src={`${import.meta.env.BASE_URL}mova-logo.svg`} alt="mova.io" className={big ? 'logoimg big' : 'logoimg'} />
export default function Logo({ big }) {
  return (
    <span className={big ? 'logo big' : 'logo'} role="img" aria-label="mova.io">
      <span className="word">mova</span>
      <span className="io"><span>io</span></span>
      <span className="tm" aria-hidden="true">™</span>
    </span>
  )
}
