import Logo from "./Logo";

const SPONSOR_URL = "https://github.com/sponsors/Nuwantha97";
const GITHUB_REPO_URL = "https://github.com/dilminidasunika/movie_recommendation_system";

export default function Footer({ hasStickySubmit = false }) {
  return (
    <footer className={`site-footer ${hasStickySubmit ? "with-sticky-bar" : ""}`.trim()}>
      <div className="footer-inner">
        <div className="footer-brand">
          <div className="footer-brand-title">
            <Logo size={20} />
            <strong>DualLens</strong>
          </div>
          <p className="footer-tagline">
            Dual-Signal Movie Recommendation System. No accounts, nothing saved.
          </p>
        </div>

        <p className="footer-credit">
          This product uses the{" "}
          <a href="https://www.themoviedb.org" target="_blank" rel="noopener noreferrer">
            TMDB
          </a>{" "}
          API but is not endorsed or certified by TMDB.
        </p>

        <div className="footer-actions">
          {/* Official alternative: <iframe src="https://github.com/sponsors/Nuwantha97/button" title="Sponsor Nuwantha97" height="32" width="114" loading="lazy" style="border:0;border-radius:6px;"> */}
          <a
            href={SPONSOR_URL}
            className="sponsor-btn"
            target="_blank"
            rel="noopener noreferrer"
          >
            <svg
              className="heart-icon"
              viewBox="0 0 16 16"
              width="14"
              height="14"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M8 14.25l-1.04-.96C3.28 9.96 1 7.89 1 5.34 1 3.27 2.61 1.75 4.65 1.75c1.16 0 2.27.54 3.35 1.48 1.08-.94 2.19-1.48 3.35-1.48 2.04 0 3.65 1.52 3.65 3.59 0 2.55-2.28 4.62-5.96 7.95L8 14.25z" />
            </svg>
            <span>Sponsor</span>
          </a>

          <a
            href={GITHUB_REPO_URL}
            className="footer-link"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub
          </a>
        </div>
      </div>
    </footer>
  );
}
