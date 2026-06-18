// Official mova.io brand mark (public/mova-logo.png, from the mova-io/mova-cli repo).
export default function Logo({ big }) {
  return <img src={`${import.meta.env.BASE_URL}mova-logo.png`} alt="mova.io" className={big ? 'logoimg big' : 'logoimg'} />
}
