export default function Logo({ size = 32, title }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      xmlns="http://www.w3.org/2000/svg"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : "true"}
      aria-label={title}
      className="logo-mark"
    >
      <circle
        cx="12"
        cy="16"
        r="9"
        fill="var(--logo-tags, #4F5D95)"
        fillOpacity="0.14"
        stroke="var(--logo-tags, #4F5D95)"
        strokeWidth="1.75"
      />
      <circle
        cx="20"
        cy="16"
        r="9"
        fill="var(--logo-plot, #C58B2A)"
        fillOpacity="0.14"
        stroke="var(--logo-plot, #C58B2A)"
        strokeWidth="1.75"
      />
      <path
        d="M16 7.94 A9 9 0 0 1 16 24.06 A9 9 0 0 1 16 7.94 Z"
        fill="var(--logo-tags, #4F5D95)"
        fillOpacity="0.3"
      />
    </svg>
  );
}
