import bgGoldenHorizon from "../assets/images/bg_golden_horizon.jpg";

export default function HeroBanner() {
  return (
    <div className="hero-banner">
      <div className="hero-banner-bg" aria-hidden="true">
        <img
          src={bgGoldenHorizon}
          alt=""
          className="hero-banner-img"
          referrerPolicy="no-referrer"
        />
      </div>
      <div className="hero-banner-overlay" />
      <div className="hero-banner-content">
        <p className="hero-kicker">Dual-Signal Cinema Intelligence</p>
        <h2 className="hero-headline">Discover Movies You&apos;ll Truly Love</h2>
        <p className="hero-subheading">
          Pick a movie you like or describe a story you want to see. DualLens compares <strong>movie plots</strong> and <strong>tags like genres and keywords</strong> to find similar movies.
        </p>
      </div>
    </div>
  );
}
