export default function Logo({ size = 36, title, className = "" }) {
  return (
    <img
      src="/logo.png"
      alt={title || "DualLens"}
      className={`logo-img ${className}`.trim()}
      style={{ height: size, width: "auto", objectFit: "contain" }}
    />
  );
}
