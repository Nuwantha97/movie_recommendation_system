export default function ScoreBar({ label, value, kind }) {
  const has = typeof value === "number" && !Number.isNaN(value);
  const pct = has ? Math.round(Math.max(0, Math.min(1, value)) * 100) : null;
  return (
    <div
      className="score-row"
      role="meter"
      aria-label={`${label} match score`}
      aria-valuenow={has ? value : 0}
      aria-valuemin="0"
      aria-valuemax="1"
      aria-valuetext={has ? `${value.toFixed(2)} (${pct}%)` : "none"}
    >
      <span className="score-label">{label}</span>
      <div className="bar" aria-hidden="true">
        {has && (
          <div
            className={`bar-fill ${kind}`}
            style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
          />
        )}
      </div>
      <span className="score-value">{has ? value.toFixed(2) : "none"}</span>
    </div>
  );
}
